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
EV_CLEAN_CSV = PROCESSED_DIR / "tfnsw_ev_cleaned.csv"

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


def find_sa4_shapefile() -> Path:
    """Path of the unzipped SA4 shapefile (fields: SA4_CODE26, SA4_NAME26, STE_CODE26, ...)."""
    shp = next(iter(sorted(SA4_DIR.glob("*.shp"))), None)
    if shp is None:
        raise FileNotFoundError(f"No SA4 shapefile in {SA4_DIR} - run: python -m src.data_acquisition")
    return shp