"""
config.py - shared paths and source URLs. Everyone imports from here:

    from src import config as cfg
    cfg.EV_CLEAN_CSV          # data/processed/tfnsw_ev_cleaned.csv 
    cfg.find_sa4_shapefile()  # path to the ASGS SA4 .shp 

"""
from pathlib import Path

# creates folders automatically
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SA4_DIR = RAW_DIR / "abs_sa4"                              

EV_RAW_CSV = RAW_DIR / "tfnsw_ev_dec2025.csv"
EV_CLEAN_CSV = PROCESSED_DIR / "tfnsw_ev_cleaned.csv"      # AC + DC, from data_acquisition.py

# Atharva's augmentation stage output: DC chargers only, enriched via
# OpenChargeMap. He has not settled on one exact filename yet, so this
# searches a few plausible variants rather than pinning one.
DC_AUGMENTED_NAME_PATTERNS = ["dc_charger*augment*.csv", "dc_charger*.csv"]

# spatial stage outputs - kept as two separate files per charger type,
# not one combined file: DC (augmented) and AC are different audiences
# downstream (schema/load stage loads them into different tables).
AC_SA4_CSV = PROCESSED_DIR / "ac_chargers_with_sa4.csv"
DC_SA4_CSV = PROCESSED_DIR / "dc_chargers_augmented_with_sa4.csv"

# database (gitignored; rebuilt by the pipeline)
DUCKDB_PATH = DATA_DIR / "ev_nsw.duckdb"
SPATIAL_DDL = ROOT / "sql" / "spatial_schema.sql"

# source data
EV_TARGET_MONTH = "202512"                                 
EV_CKAN_APIS = [                                           
    ("data.nsw.gov.au",
     "https://data.nsw.gov.au/data/api/3/action/package_show?id=69fab867-a077-4e3d-a9ab-c169681ac877"),
    ("data.gov.au",
     "https://data.gov.au/data/api/3/action/package_show?id=nsw-2-ev-charging-locations"),
]
EV_FALLBACK_URL = (                                        
    "https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/"
    "resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv"
)

SA4_URL = (                                                
    "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/"
    "edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files/"
    "SA4_2026_AUST_SHP_GDA2020.zip"
)
SA4_CRS = "EPSG:7844"                                      
NSW_STATE_CODE = "1"                                       
# generous NSW extent, used only to catch grossly wrong coordinates
NSW_BBOX = {"lat": (-38.0, -27.5), "lon": (140.5, 154.2)}  


def find_sa4_shapefile() -> Path:
    """Path of the unzipped SA4 shapefile (fields: SA4_CODE26, SA4_NAME26, STE_CODE26, ...)."""
    shp = next(iter(sorted(SA4_DIR.glob("*.shp"))), None)
    if shp is None:
        raise FileNotFoundError(f"No SA4 shapefile in {SA4_DIR} - run: python -m src.data_acquisition")
    return shp


def find_dc_augmented_csv() -> Path | None:
    """Path to Atharva's augmented DC-charger CSV, if it has been dropped into
    data/processed/ yet. Returns None (not an error) when it hasn't - the
    spatial stage can still run its AC join without it."""
    for pattern in DC_AUGMENTED_NAME_PATTERNS:
        hit = next(iter(sorted(PROCESSED_DIR.glob(pattern))), None)
        if hit is not None:
            return hit
    return None