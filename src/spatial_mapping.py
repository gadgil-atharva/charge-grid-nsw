"""
spatial_mapping.py - assign every cleaned EV charger to its ASGS SA4 region.

  1. Load the ASGS SA4 boundaries with DuckDB's spatial extension (ST_Read)
  2. Build point geometry from the cleaned latitude/longitude
  3. Join points to polygons, then persist to DuckDB for spatial querying

  input   data/processed/tfnsw_ev_cleaned.csv   (from data_acquisition.py)
  output  data/processed/tfnsw_ev_with_sa4.csv  (chargers + sa4_code/sa4_name)
          data/ev_nsw.duckdb                    (sa4_region, charger_location,
                                                 charger_sa4_assignment)

Run after data_acquisition.py:

    python -m src.spatial_mapping
"""
import argparse
import logging
import sys

import duckdb

from src import config as cfg

log = logging.getLogger("spatial_mapping")

# The nearest-boundary fallback distance, in metres. Wide enough to absorb the
# generalised ABS coastline (a foreshore charger can sit a metre or two into
# mapped water) but far too narrow to bridge a real gap between two regions.
NEAREST_TOLERANCE_M = 100.0


# CONNECTION
def connect(db_path=None) -> duckdb.DuckDBPyConnection:
    """Open the DuckDB file with the spatial extension loaded.

    LOAD is per-connection state and is NOT stored inside the .duckdb file, so
    every session that reads a GEOMETRY column has to issue it again.
    """
    db_path = db_path or cfg.DUCKDB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("INSTALL spatial;")
    con.execute("LOAD spatial;")
    return con


def apply_ddl(con) -> None:
    con.execute(cfg.SPATIAL_DDL.read_text(encoding="utf-8"))


# BOUNDARIES
def verify_crs(con, shp) -> str:
    """Read the shapefile's declared CRS and check it is what config expects.

    A CRS mismatch is the one spatial-join failure that raises no error: it just
    returns wrong or empty results, so we assert instead of assuming.
    """
    layers = con.execute("SELECT layers FROM ST_Read_Meta(?)", [str(shp)]).fetchone()[0]
    crs = layers[0]["geometry_fields"][0]["crs"]
    auth = f"{crs['auth_name']}:{crs['auth_code']}"
    if auth != cfg.SA4_CRS:
        raise RuntimeError(f"SA4 boundaries are {auth}, expected {cfg.SA4_CRS} - reprojection needed")
    return auth


def load_sa4(con, shp) -> None:
    """Load every Australian SA4, not just NSW.

    Filtering to NSW up front would turn a charger sitting just over a state
    border into an 'unmatched' row that looks like a bug, instead of resolving
    to its true region. The state split is reported as a check instead.
    """
    con.execute(
        """
        INSERT INTO sa4_region
        SELECT SA4_CODE26, SA4_NAME26, GCC_CODE26, GCC_NAME26, STE_CODE26, STE_NAME26,
               CAST(AREASQKM26 AS DOUBLE), geom IS NULL, geom
        FROM ST_Read(?)
        """,
        [str(shp)],
    )
    # The 'Migratory - Offshore - Shipping' and 'No usual address' codes carry no
    # geometry; they stay in the table for completeness but never join.
    kept, special = con.execute(
        "SELECT count(*) FILTER (WHERE NOT is_special_purpose), "
        "       count(*) FILTER (WHERE is_special_purpose) FROM sa4_region"
    ).fetchone()
    log.info("SA4 regions: %d with geometry, %d special-purpose (excluded)", kept, special)


# CHARGER POINTS
def load_points(con, csv_path) -> None:
    """Build point geometry from the cleaned coordinates.

    ST_Point takes (x, y) = (longitude, latitude), which is the reverse of the
    column order in the source. Passing them the wrong way round puts every NSW
    charger in Siberia and silently matches nothing, so the bounding-box check
    below exists to make that failure loud rather than invisible.

    data_acquisition.py already repairs swapped/unsigned coordinates and drops
    rows outside NSW, so this is a defensive re-check on its output.
    """
    con.execute(
        f"""
        INSERT INTO charger_location
        WITH flagged AS (
            SELECT charger_id,
                   CAST(latitude AS DOUBLE)  AS lat,
                   CAST(longitude AS DOUBLE) AS lon,
                   CASE
                       WHEN latitude IS NULL OR longitude IS NULL THEN 'missing_coordinate'
                       WHEN latitude = 0 OR longitude = 0         THEN 'zero_sentinel'
                       WHEN CAST(longitude AS DOUBLE) NOT BETWEEN {cfg.NSW_BBOX['lon'][0]} AND {cfg.NSW_BBOX['lon'][1]}
                         OR CAST(latitude AS DOUBLE)  NOT BETWEEN {cfg.NSW_BBOX['lat'][0]} AND {cfg.NSW_BBOX['lat'][1]}
                                                                  THEN 'outside_nsw_bbox'
                   END AS reject
            FROM read_csv_auto(?, header = true)
        )
        SELECT charger_id, lat, lon, reject IS NULL, reject,
               CASE WHEN reject IS NULL THEN ST_Point(lon, lat) END
        FROM flagged
        """,
        [str(csv_path)],
    )
    bad = con.execute("SELECT count(*) FROM charger_location WHERE NOT coord_valid").fetchone()[0]
    if bad:
        log.warning("%d charger(s) failed the coordinate screen and will not be joined", bad)


# THE JOIN
def run_join(con, tolerance_m: float) -> None:
    """Point-in-polygon first, then a bounded nearest-boundary fallback.

    ST_Within is the correct point-in-polygon predicate. ST_Intersects is not
    used as the primary test because it is also true for a point lying exactly
    on a shared edge, which would match that charger to both neighbouring SA4s
    and duplicate the row downstream.
    """
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE pass1 AS
        SELECT c.charger_id, s.sa4_code
        FROM charger_location c
        JOIN sa4_region s ON s.geom IS NOT NULL AND ST_Within(c.geom, s.geom)
        WHERE c.coord_valid
        """
    )
    # SA4s tile the country without overlapping, so more than one match means a
    # boundary artefact. Fail loudly rather than let a fan-out inflate the data.
    dupes = con.execute(
        "SELECT count(*) FROM (SELECT charger_id FROM pass1 GROUP BY charger_id HAVING count(*) > 1)"
    ).fetchone()[0]
    if dupes:
        raise RuntimeError(f"{dupes} charger(s) matched more than one SA4 polygon")

    # Under DE-9IM a point exactly on (or just outside) a boundary is not
    # 'within' it, which is what happens on a generalised coastline. Snap those
    # to the nearest polygon, but only within tolerance, and keep the distance
    # so the snap stays auditable.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE pass2 AS
        WITH residual AS (
            SELECT charger_id, geom FROM charger_location
            WHERE coord_valid AND charger_id NOT IN (SELECT charger_id FROM pass1)
        ),
        ranked AS (
            SELECT r.charger_id, s.sa4_code,
                   -- ST_Distance_Sphere takes points only, so measure to the
                   -- closest point ON the polygon to get true metres, not degrees.
                   ST_Distance_Sphere(r.geom, ST_ClosestPoint(s.geom, r.geom)) AS dist_m,
                   row_number() OVER (PARTITION BY r.charger_id
                                      ORDER BY ST_Distance(r.geom, s.geom)) AS rn
            FROM residual r CROSS JOIN sa4_region s
            WHERE s.geom IS NOT NULL
        )
        SELECT charger_id, sa4_code, dist_m FROM ranked WHERE rn = 1 AND dist_m <= {tolerance_m}
        """
    )

    # LEFT JOIN from charger_location, never an inner join: an inner join would
    # silently delete unmatched chargers instead of leaving them countable.
    con.execute(
        """
        INSERT INTO charger_sa4_assignment
        SELECT c.charger_id,
               COALESCE(p1.sa4_code, p2.sa4_code),
               CASE WHEN p1.sa4_code IS NOT NULL THEN 'within'
                    WHEN p2.sa4_code IS NOT NULL THEN 'nearest_boundary'
                    ELSE 'unmatched' END,
               CASE WHEN p1.sa4_code IS NOT NULL THEN 0.0 ELSE p2.dist_m END
        FROM charger_location c
        LEFT JOIN pass1 p1 USING (charger_id)
        LEFT JOIN pass2 p2 USING (charger_id)
        """
    )


def build_index(con) -> None:
    """R-tree on the SA4 geometry.

    At 1,958 points against 89 polygons the join is already sub-second, so this
    earns nothing now; it is here for the repeated range and nearest-neighbour
    queries planned for Assignment 2.
    """
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_sa4_geom ON sa4_region USING RTREE (geom)")
    except duckdb.Error as exc:
        log.warning("R-tree index not created: %s", exc)


# OUTPUT
def export_csv(con, csv_in, csv_out) -> None:
    """Write the cleaned chargers back out with their SA4 columns attached."""
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    # COPY ... TO does not accept a bound parameter for the target path, so it
    # is escaped and inlined; the input path stays parameterised.
    target = str(csv_out).replace("'", "''")
    con.execute(
        f"""
        COPY (
            SELECT e.*, a.sa4_code, s.sa4_name, s.gcc_name, a.match_method, a.match_distance_m
            FROM read_csv_auto(?, header = true) e
            LEFT JOIN charger_sa4_assignment a USING (charger_id)
            LEFT JOIN sa4_region s USING (sa4_code)
            ORDER BY e.charger_id
        ) TO '{target}' (HEADER, DELIMITER ',')
        """,
        [str(csv_in)],
    )
    log.info("wrote %s", csv_out)


def report(con) -> dict:
    """Coverage and sanity checks - these are the numbers quoted in the report."""
    total, assigned = con.execute(
        "SELECT count(*), count(sa4_code) FROM charger_sa4_assignment"
    ).fetchone()
    log.info("assigned %d of %d chargers (%.1f%%)", assigned, total, 100.0 * assigned / total)
    for method, n in con.execute(
        "SELECT match_method, count(*) FROM charger_sa4_assignment GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        log.info("  %-18s %d", method, n)
    for state, n in con.execute(
        "SELECT s.state_name, count(*) FROM charger_sa4_assignment a "
        "JOIN sa4_region s USING (sa4_code) GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        log.info("  state: %-22s %d", state, n)
    for cid, name, d in con.execute(
        "SELECT a.charger_id, s.sa4_name, round(a.match_distance_m, 2) FROM charger_sa4_assignment a "
        "JOIN sa4_region s USING (sa4_code) WHERE a.match_method = 'nearest_boundary'"
    ).fetchall():
        log.info("  snapped charger %s -> %s (%.2f m)", cid, name, d)
    return {"total": total, "assigned": assigned}


# ENTRY POINT
def run(tolerance_m: float = NEAREST_TOLERANCE_M, db_path=None) -> dict:
    if not cfg.EV_CLEAN_CSV.exists():
        raise FileNotFoundError(f"{cfg.EV_CLEAN_CSV} missing - run: python -m src.data_acquisition")
    shp = cfg.find_sa4_shapefile()

    con = connect(db_path)
    try:
        apply_ddl(con)
        log.info("SA4 source CRS verified: %s", verify_crs(con, shp))
        load_sa4(con, shp)
        load_points(con, cfg.EV_CLEAN_CSV)
        run_join(con, tolerance_m)
        build_index(con)
        export_csv(con, cfg.EV_CLEAN_CSV, cfg.EV_SA4_CSV)
        stats = report(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Join EV chargers to ASGS SA4 regions.")
    ap.add_argument("--tolerance", type=float, default=NEAREST_TOLERANCE_M,
                    help="nearest-boundary snap tolerance in metres")
    args = ap.parse_args()
    try:
        run(tolerance_m=args.tolerance)
    except Exception as exc:
        log.error("FAILED: %s", exc)
        sys.exit(1)
