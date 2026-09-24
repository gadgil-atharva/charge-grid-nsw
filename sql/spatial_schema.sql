-- ---------------------------------------------------------------------
-- spatial_schema.sql - tables owned by the spatial stage (spatial_mapping.py)
--
-- These are the geometry-bearing tables only. The full relational schema for
-- the assignment lives in ddl_schema.sql; these three are meant to be folded
-- into it, with charger_location.charger_id as the join key.
--
-- CRS: every GEOMETRY column here holds EPSG:7844 (GDA2020) lon/lat degrees.
-- DuckDB's GEOMETRY type carries no SRID, so that is a contract enforced by
-- the loader, not by the engine. Do not insert projected or lat/lon-swapped
-- geometry into these columns.
--
-- The spatial extension must be loaded in EVERY session that reads them:
--     INSTALL spatial; LOAD spatial;
-- ---------------------------------------------------------------------

INSTALL spatial;
LOAD spatial;

DROP TABLE IF EXISTS charger_sa4_assignment;
DROP TABLE IF EXISTS charger_location;
DROP TABLE IF EXISTS sa4_region;

-- ASGS Edition 4 (2026) SA4 boundaries, all states.
-- Special-purpose codes ('Migratory - Offshore - Shipping', 'No usual
-- address') have no geometry; they are kept for completeness and flagged so
-- they can never take part in a spatial predicate.
CREATE TABLE sa4_region (
    sa4_code            VARCHAR PRIMARY KEY,
    sa4_name            VARCHAR NOT NULL,
    gcc_code            VARCHAR,
    gcc_name            VARCHAR,
    state_code          VARCHAR,
    state_name          VARCHAR,
    area_sqkm           DOUBLE,
    is_special_purpose  BOOLEAN NOT NULL,   -- TRUE => geom IS NULL
    geom                GEOMETRY            -- EPSG:7844
);

-- One row per cleaned charger, carrying only its point geometry. Attributes
-- stay in the cleaning stage's output so the spatial stage never mutates them.
CREATE TABLE charger_location (
    charger_id      BIGINT PRIMARY KEY,     -- from tfnsw_ev_cleaned.csv
    latitude        DOUBLE,
    longitude       DOUBLE,
    coord_valid     BOOLEAN NOT NULL,
    coord_reject    VARCHAR,                -- reason when coord_valid = FALSE
    geom            GEOMETRY                -- EPSG:7844; NULL iff not valid
);

-- The join result, kept as its own relation rather than a column bolted onto
-- the charger table, so match provenance stays queryable and the join can be
-- re-run without touching source data.
--   match_method: 'within' | 'nearest_boundary' | 'unmatched'
CREATE TABLE charger_sa4_assignment (
    charger_id          BIGINT PRIMARY KEY,
    sa4_code            VARCHAR,            -- NULL when 'unmatched'
    match_method        VARCHAR NOT NULL,
    match_distance_m    DOUBLE,             -- 0.0 for 'within', else metres
    FOREIGN KEY (charger_id) REFERENCES charger_location (charger_id),
    FOREIGN KEY (sa4_code)   REFERENCES sa4_region (sa4_code)
);
