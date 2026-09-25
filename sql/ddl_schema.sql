-- COMP5339 Assignment 1 — EV Charger Database Schema
-- Normalized relational design for NSW EV charger data (AC + DC),
-- SA4/GCC region tagging, and DC-charger augmentation.

INSTALL spatial;
LOAD spatial;

CREATE SEQUENCE IF NOT EXISTS charger_pk_seq START 1;

-- ABS ASGS regions (SA4 level), with parent Greater Capital City grouping
CREATE TABLE regions (
    sa4_code INTEGER PRIMARY KEY,
    sa4_name VARCHAR NOT NULL,
    gcc_name VARCHAR NOT NULL
);

-- Charging network operators (Tesla, Chargefox, NRMA, etc.)
CREATE TABLE operators (
    operator_id   INTEGER PRIMARY KEY,
    operator_name VARCHAR NOT NULL UNIQUE
);

-- Physical charging sites (a location can host multiple chargers, AC and/or DC)
CREATE TABLE sites (
    site_id                  INTEGER PRIMARY KEY,
    station_address          VARCHAR,
    latitude                 DOUBLE NOT NULL,
    longitude                DOUBLE NOT NULL,
    lga_name                 VARCHAR,
    postcode                 VARCHAR,
    sa4_code                 INTEGER REFERENCES regions(sa4_code),
    spatial_match_method     VARCHAR,   -- e.g. 'within', 'nearest_boundary'
    spatial_match_distance_m DOUBLE,     -- distance used by the spatial join, if not a direct 'within'
    geom                     GEOMETRY   -- point geometry (from lat/long), for assignment 2 spatial queries
);

-- Individual charger units. source_charger_id is only unique WITHIN a charger_type
-- (AC and DC were numbered independently upstream), so charger_pk is the real key.
CREATE TABLE chargers (
    charger_pk        INTEGER PRIMARY KEY DEFAULT nextval('charger_pk_seq'),
    source_charger_id INTEGER NOT NULL,
    charger_type      VARCHAR NOT NULL CHECK (charger_type IN ('AC', 'DC')),
    site_id           INTEGER REFERENCES sites(site_id),
    operator_id       INTEGER REFERENCES operators(operator_id),
    station_name      VARCHAR,
    number_of_plugs   INTEGER,
    current_type      VARCHAR,
    rating_kw         DOUBLE,
    is_upcoming       BOOLEAN,
    source            VARCHAR,   -- original TfNSW dataset/source label
    UNIQUE (source_charger_id, charger_type)
);

-- A charger can support multiple connector/plug types (from OCM augmentation).
-- One row per DISTINCT plug type per charger (source strings had duplicates — deduped on load).
CREATE TABLE charger_plug_types (
    charger_pk INTEGER REFERENCES chargers(charger_pk),
    plug_type  VARCHAR NOT NULL,
    PRIMARY KEY (charger_pk, plug_type)
);

-- Augmentation data — only populated for DC fast chargers that were enriched via Open Charge Map.
CREATE TABLE charger_augmentation (
    charger_pk                 INTEGER PRIMARY KEY REFERENCES chargers(charger_pk),
    ocm_id                     INTEGER,
    ocm_operator               VARCHAR,
    usage_cost_raw             VARCHAR,   -- free text, unit/format varies by operator — not parsed
    ocm_plug_count             INTEGER,
    augmentation_match_method  VARCHAR   -- e.g. 'Proximity + Operator Match', 'No Match'
);
