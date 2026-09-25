"""
COMP5339 Assignment 1 — load AC and DC charger CSVs into the DuckDB schema.



Assumes:
  - schema.sql            (DDL, run first to create tables)
  - ac_chargers_with_sa4.csv
  - dc_chargers_augmented_with_sa4.csv
are all in the same folder as this script (adjust paths below if not).
"""

import duckdb
import pandas as pd

DB_PATH = "ev_chargers.db"
AC_CSV = "D:\\Data Engineering Assignment\\data\\processed\\ac_chargers_with_sa4.csv"
DC_CSV = "D:\\Data Engineering Assignment\\data\\processed\\dc_chargers_augmented_with_sa4.csv"


def load_csvs():
    ac = pd.read_csv(AC_CSV)
    dc = pd.read_csv(DC_CSV)
    # The DC file's second (spatial-join) match method column got auto-suffixed
    # when it was merged with the augmentation match_method column upstream.
    dc = dc.rename(columns={
        "match_method": "augmentation_match_method",
        "match_method_1": "spatial_match_method",
        "match_distance_m": "spatial_match_distance_m",
    })
    ac = ac.rename(columns={
        "match_method": "spatial_match_method",
        "match_distance_m": "spatial_match_distance_m",
    })
    return ac, dc


def build_regions(con, ac, dc):
    regions_df = (
        pd.concat([ac[["sa4_code", "sa4_name", "gcc_name"]],
                   dc[["sa4_code", "sa4_name", "gcc_name"]]])
        .drop_duplicates(subset="sa4_code")
        .sort_values("sa4_code")
    )
    con.register("regions_stage", regions_df)
    con.execute("INSERT INTO regions SELECT * FROM regions_stage")


def build_operators(con, ac, dc):
    names = sorted(set(ac["operator"].dropna()) | set(dc["operator"].dropna()))
    operators_df = pd.DataFrame({
        "operator_id": range(1, len(names) + 1),
        "operator_name": names,
    })
    con.register("operators_stage", operators_df)
    con.execute("INSERT INTO operators SELECT * FROM operators_stage")
    return dict(zip(operators_df["operator_name"], operators_df["operator_id"]))


def build_sites(con, ac, dc):
    cols = ["site_id", "station_address", "latitude", "longitude", "lga_name",
            "postcode", "sa4_code", "spatial_match_method", "spatial_match_distance_m"]
    sites_df = (
        pd.concat([ac[cols], dc[cols]])
        .drop_duplicates(subset="site_id")
        .sort_values("site_id")
    )
    con.register("sites_stage", sites_df)
    con.execute("""
        INSERT INTO sites
        SELECT site_id, station_address, latitude, longitude, lga_name,
               postcode, sa4_code, spatial_match_method, spatial_match_distance_m,
               ST_Point(longitude, latitude) AS geom
        FROM sites_stage
    """)   


def build_chargers(con, ac, dc, operator_ids):
    def prep(df, charger_type):
        out = pd.DataFrame({
            "source_charger_id": df["charger_id"],
            "charger_type": charger_type,
            "site_id": df["site_id"],
            "operator_id": df["operator"].map(operator_ids),
            "station_name": df["station_name"],
            "number_of_plugs": df["number_of_plugs"],
            "current_type": df["current_type"],
            "rating_kw": df["rating_kw"],
            "is_upcoming": df["is_upcoming"],
            "source": df["source"],
        })
        return out

    chargers = pd.concat([prep(ac, "AC"), prep(dc, "DC")], ignore_index=True)
    # charger_pk is auto-assigned by the sequence default; insert into the
    # non-PK columns explicitly and let DuckDB fill charger_pk.
    con.register("chargers_stage", chargers)
    con.execute("""
        INSERT INTO chargers (
            source_charger_id, charger_type, site_id, operator_id,
            station_name, number_of_plugs, current_type, rating_kw,
            is_upcoming, source
        )
        SELECT source_charger_id, charger_type, site_id, operator_id,
               station_name, number_of_plugs, current_type, rating_kw,
               is_upcoming, source
        FROM chargers_stage
    """)


def build_plug_types(con, dc):
    """Split and de-duplicate the messy comma-separated ocm_plug_types field,
    then map back to the surrogate charger_pk via (source_charger_id, charger_type)."""
    id_map = con.execute("""
        SELECT charger_pk, source_charger_id
        FROM chargers WHERE charger_type = 'DC'
    """).fetchdf()
    id_lookup = dict(zip(id_map["source_charger_id"], id_map["charger_pk"]))

    rows = []
    for _, row in dc.dropna(subset=["ocm_plug_types"]).iterrows():
        if row["ocm_plug_types"] == "Unknown":
            continue
        charger_pk = id_lookup.get(row["charger_id"])
        if charger_pk is None:
            continue
        for plug in {p.strip() for p in row["ocm_plug_types"].split(",")}:
            rows.append({"charger_pk": charger_pk, "plug_type": plug})

    plug_df = pd.DataFrame(rows).drop_duplicates()
    con.register("plug_stage", plug_df)
    con.execute("INSERT INTO charger_plug_types SELECT * FROM plug_stage")


def build_augmentation(con, dc):
    id_map = con.execute("""
        SELECT charger_pk, source_charger_id
        FROM chargers WHERE charger_type = 'DC'
    """).fetchdf()
    id_lookup = dict(zip(id_map["source_charger_id"], id_map["charger_pk"]))

    aug = pd.DataFrame({
        "charger_pk": dc["charger_id"].map(id_lookup),
        "ocm_id": dc["ocm_id"],
        "ocm_operator": dc["ocm_operator"],
        "usage_cost_raw": dc["usage_cost"],
        "ocm_plug_count": dc["ocm_plug_count"],
        "augmentation_match_method": dc["augmentation_match_method"],
    })
    con.register("aug_stage", aug)
    con.execute("INSERT INTO charger_augmentation SELECT * FROM aug_stage")

def run_sample_queries(con):
    """Sanity-check the loaded schema with a representative set of query patterns
    covering aggregation, multi-table joins, data-quality checks, and filtering."""
    queries = [
        ("Total chargers by type (AC vs DC)",
         "SELECT charger_type, count(*) AS n FROM chargers GROUP BY charger_type ORDER BY n DESC"),

        ("Chargers per operator, top 10",
         """SELECT o.operator_name, count(*) AS n FROM chargers c
            JOIN operators o ON c.operator_id = o.operator_id
            GROUP BY o.operator_name ORDER BY n DESC LIMIT 10"""),

        ("Chargers per SA4 region, top 10",
         """SELECT r.sa4_name, count(*) AS n FROM chargers c
            JOIN sites s ON c.site_id = s.site_id
            JOIN regions r ON s.sa4_code = r.sa4_code
            GROUP BY r.sa4_name ORDER BY n DESC LIMIT 10"""),

        ("Chargers by Greater Capital City area (Sydney vs rest of NSW)",
         """SELECT r.gcc_name, count(*) AS n FROM chargers c
            JOIN sites s ON c.site_id = s.site_id
            JOIN regions r ON s.sa4_code = r.sa4_code
            GROUP BY r.gcc_name ORDER BY n DESC"""),

        ("Chargers by type within each GCC area",
         """SELECT r.gcc_name, c.charger_type, count(*) AS n FROM chargers c
            JOIN sites s ON c.site_id = s.site_id
            JOIN regions r ON s.sa4_code = r.sa4_code
            GROUP BY r.gcc_name, c.charger_type ORDER BY r.gcc_name, n DESC"""),

        ("Average power rating (kW) by charger type",
         "SELECT charger_type, round(avg(rating_kw),1) AS avg_kw FROM chargers GROUP BY charger_type"),

        ("Highest-power charger per operator, top 10",
         """SELECT o.operator_name, max(c.rating_kw) AS max_kw FROM chargers c
            JOIN operators o ON c.operator_id = o.operator_id
            GROUP BY o.operator_name ORDER BY max_kw DESC LIMIT 10"""),

        ("Sites hosting more than one charger",
         """SELECT site_id, count(*) AS n FROM chargers
            GROUP BY site_id HAVING count(*) > 1 ORDER BY n DESC"""),

        ("Sites offering BOTH AC and DC charging",
         """SELECT site_id, count(DISTINCT charger_type) AS types
            FROM chargers GROUP BY site_id HAVING count(DISTINCT charger_type) = 2"""),

        ("Operators present in both AC and DC fleets",
         """SELECT o.operator_name FROM operators o
            WHERE o.operator_id IN (SELECT operator_id FROM chargers WHERE charger_type='AC')
              AND o.operator_id IN (SELECT operator_id FROM chargers WHERE charger_type='DC')
            ORDER BY o.operator_name"""),

        ("Chargers with missing operator (data quality check)",
         "SELECT count(*) AS n FROM chargers WHERE operator_id IS NULL"),

        ("Chargers with missing site/region link (data quality check)",
         """SELECT count(*) AS n FROM chargers c
            LEFT JOIN sites s ON c.site_id = s.site_id WHERE s.site_id IS NULL"""),

        ("Distinct connector/plug types available (from augmentation)",
         "SELECT DISTINCT plug_type FROM charger_plug_types ORDER BY plug_type"),

        ("Chargers count per plug type",
         """SELECT plug_type, count(*) AS n FROM charger_plug_types
            GROUP BY plug_type ORDER BY n DESC"""),

        ("Chargers supporting CHAdeMO specifically",
         """SELECT count(DISTINCT charger_pk) AS n FROM charger_plug_types
            WHERE plug_type = 'CHAdeMO'"""),

        ("DC chargers with no successful augmentation match",
         """SELECT count(*) AS n FROM charger_augmentation
            WHERE augmentation_match_method = 'No Match'"""),

        ("DC chargers with known usage cost text",
         """SELECT c.charger_pk, o.operator_name, a.usage_cost_raw
            FROM chargers c
            JOIN charger_augmentation a ON c.charger_pk = a.charger_pk
            JOIN operators o ON c.operator_id = o.operator_id
            WHERE a.usage_cost_raw IS NOT NULL LIMIT 5"""),

        ("Fast chargers only (>150kW), by operator",
         """SELECT o.operator_name, count(*) AS n FROM chargers c
            JOIN operators o ON c.operator_id = o.operator_id
            WHERE c.rating_kw > 150 GROUP BY o.operator_name ORDER BY n DESC"""),

        ("Region with highest density of DC fast chargers",
         """SELECT r.sa4_name, count(*) AS n FROM chargers c
            JOIN sites s ON c.site_id = s.site_id
            JOIN regions r ON s.sa4_code = r.sa4_code
            WHERE c.charger_type = 'DC' GROUP BY r.sa4_name ORDER BY n DESC LIMIT 5"""),

        ("Full detail for one sample charger (all tables joined)",
         """SELECT c.charger_pk, c.charger_type, o.operator_name, s.station_address,
                   r.sa4_name, r.gcc_name, a.usage_cost_raw
            FROM chargers c
            JOIN operators o ON c.operator_id = o.operator_id
            JOIN sites s ON c.site_id = s.site_id
            JOIN regions r ON s.sa4_code = r.sa4_code
            LEFT JOIN charger_augmentation a ON c.charger_pk = a.charger_pk
            WHERE c.charger_type = 'DC' LIMIT 1"""),
    ]

    print("\nSample query check:")
    for i, (desc, q) in enumerate(queries, 1):
        result = con.execute(q).fetchdf()
        print(f"[{i}] {desc} -> {len(result)} row(s)")


def main():
    con = duckdb.connect(DB_PATH)
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(project_root, "sql", "ddl_schema.sql")
    for statement in open(schema_path).read().split(";"):
        statement = statement.strip()
        if statement:
            con.execute(statement)

    print("Resolved schema path:", schema_path)
    print("Tables after DDL:", con.execute("SHOW TABLES").fetchdf())

    ac, dc = load_csvs()
    build_regions(con, ac, dc)
    operator_ids = build_operators(con, ac, dc)
    build_sites(con, ac, dc)
    build_chargers(con, ac, dc, operator_ids)
    build_plug_types(con, dc)
    build_augmentation(con, dc)

    print("Row counts:")
    for t in ["regions", "operators", "sites", "chargers",
              "charger_plug_types", "charger_augmentation"]:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n}")

    run_sample_queries(con)
    con.close()


if __name__ == "__main__":
    main()