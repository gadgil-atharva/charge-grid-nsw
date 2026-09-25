"""
data_acquisition.py - acquire + clean the NSW EV charger data.

  1. Acquisition (no manual download)
       - TfNSW EV Charging Locations, Dec 2025 release -> data/raw/tfnsw_ev_dec2025.csv
       - ABS ASGS Edition 4 SA4 boundaries (shapefile)  -> data/raw/abs_sa4/
  2. Cleaning -> data/processed/tfnsw_ev_cleaned.csv  

"""
import argparse
import io
import logging
import re
import sys
import time
import zipfile
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

from src import config as cfg

log = logging.getLogger("data_acquisition")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}


# ACQUISITION
def fetch(url: str) -> bytes:
    """GET with 3 attempts; refuses HTML pages (login walls / error pages)."""
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(15, 180))
            r.raise_for_status()
            if r.content[:20].lstrip().lower().startswith((b"<!doctype", b"<html")):
                raise RuntimeError("got a web page instead of data")
            return r.content
        except Exception as exc:
            log.warning("download attempt %d failed for %s: %s", attempt, url, exc)
            if attempt == 3:
                raise
            time.sleep(2 * attempt)


def find_ev_url(month: str = cfg.EV_TARGET_MONTH) -> str:
    """Ask the CKAN catalogue for the resource whose file name carries the December 2025 date."""
    for name, api in cfg.EV_CKAN_APIS:
        try:
            resources = requests.get(api, headers=HEADERS, timeout=60).json()["result"]["resources"]
        except Exception as exc:
            log.warning("catalogue %s unavailable: %s", name, exc)
            continue
        hits = []
        for res in resources:
            fname = urlparse(res.get("url", "")).path.split("/")[-1]
            m = re.search(r"(20\d{2})(\d{2})\d{2}", fname)
            if m and m.group(1) + m.group(2) == month:
                hits.append((fname, res["url"]))
        if hits:
            return max(hits)[1]
    log.warning("catalogue lookup failed - using the pinned December 2025 URL")
    return cfg.EV_FALLBACK_URL


def acquire(force: bool = False) -> None:
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if force or not cfg.EV_RAW_CSV.exists():
        url = find_ev_url()
        log.info("downloading EV chargers: %s", url)
        cfg.EV_RAW_CSV.write_bytes(fetch(url))
    else:
        log.info("EV file already downloaded")

    if force or not list(cfg.SA4_DIR.glob("*.shp")):
        log.info("downloading ABS SA4 boundaries: %s", cfg.SA4_URL)
        zipfile.ZipFile(io.BytesIO(fetch(cfg.SA4_URL))).extractall(cfg.SA4_DIR)
        cfg.find_sa4_shapefile()                       
    else:
        log.info("SA4 boundaries already downloaded")


# CLEANING
COLUMN_ALIASES = {   
    "objectid": "object_id", "station_name": "station_name", "station_address": "station_address",
    "operator": "operator", "number_of_plugs": "number_of_plugs", "charger_type": "charger_type",
    "charger_rating": "charger_rating", "latitude": "latitude", "longitude": "longitude",
    "lganame": "lga_name", "pcode": "postcode", "source": "source",
    "name": "station_name", "address": "station_address", "lat": "latitude", "lon": "longitude",
    "lng": "longitude", "postcode": "postcode", "lga_name": "lga_name", "plugs": "number_of_plugs",
}
EXPECTED = ["station_name", "station_address", "operator", "number_of_plugs", "charger_type",
            "charger_rating", "latitude", "longitude", "lga_name", "postcode", "source"]
PLACEHOLDERS = {"", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "?", "tbc", "tbd", "unknown"}
OPERATOR_RULES = [(r"nrma", "NRMA"), (r"chargefox", "Chargefox"), (r"evie", "Evie Networks"),
                  (r"tesla", "Tesla"), (r"ampol|ampcharge", "Ampol"), (r"\bbp\b", "BP Pulse"),
                  (r"jolt", "Jolt"), (r"exploren", "Exploren"), (r"engie", "Engie"),
                  (r"evenergi", "Evenergi"), (r"shell", "Shell Recharge"), (r"7.?eleven", "7-Eleven"),
                  (r"viva energy", "Viva Energy"), (r"fast cities", "Fast Cities")]
NSW = {"lat": (-37.7, -27.9), "lon": (140.8, 153.8)}      # rough NSW bounding box


def snake(col) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(col).replace("\ufeff", "").strip().lower()).strip("_")


def clean_text(x):
    """Trim, collapse whitespace, turn placeholders like 'N/A' / 'TBC' / '-' into NaN."""
    if pd.isna(x):
        return np.nan
    s = re.sub(r"\s+", " ", str(x).replace("\u00a0", " ")).strip()
    return np.nan if s.lower() in PLACEHOLDERS else s


def load_raw() -> pd.DataFrame:
    df = pd.read_csv(cfg.EV_RAW_CSV, dtype=str, encoding_errors="replace")
    df = df.rename(columns=lambda c: COLUMN_ALIASES.get(snake(c), snake(c)))
    if not {"latitude", "longitude"} <= set(df.columns):
        raise ValueError(f"No latitude/longitude columns found. Columns are: {list(df.columns)}")
    for c in EXPECTED:                                   
        if c not in df.columns:
            log.warning("column '%s' not in raw file", c)
            df[c] = np.nan
    return df


def parse_rating(s):
    """'22 kW' -> 22 | '22' -> 22 | '2x350kW & 2x175kW' -> 350 (highest plug power) | 'AC' -> NaN"""
    if not isinstance(s, str):
        return np.nan
    kw = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*kw", s, flags=re.I)]
    if kw:
        return max(kw)
    return float(s) if re.fullmatch(r"\d+(?:\.\d+)?", s.strip()) else np.nan


def postcode_from_address(addr):
    """Last 2xxx number in the address text ('... Artarmon NSW 2064, Australia' -> '2064')."""
    found = re.findall(r"\b2\d{3}\b", addr) if isinstance(addr, str) else []
    return found[-1] if found else np.nan


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    st = {"raw_rows": len(df)}
    df = df.copy()
    df["source_row"] = np.arange(len(df)) + 2            

    # text / missing values
    before = df[EXPECTED].isna().sum().sum()
    for c in EXPECTED:
        df[c] = df[c].map(clean_text)
    st["placeholder_cells_set_to_null"] = int(df[EXPECTED].isna().sum().sum() - before)

    # types
    for c in ("latitude", "longitude"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    plugs = pd.to_numeric(df["number_of_plugs"], errors="coerce")
    st["invalid_plug_counts_nulled"] = int((plugs.notna() & (plugs <= 0)).sum())
    df["number_of_plugs"] = plugs.where(plugs > 0).astype("Int64")
    df["rating_kw"] = df["charger_rating"].map(parse_rating).astype(float)
    df["postcode"] = df["postcode"].str.extract(r"(\d{4})")[0]
    no_pc = df["postcode"].isna()                         
    df.loc[no_pc, "postcode"] = df.loc[no_pc, "station_address"].map(postcode_from_address)
    st["postcodes_filled_from_address"] = int(no_pc.sum() - df["postcode"].isna().sum())

    # charger type (AC / DC) and status
    t = df["charger_type"].fillna("").astype(str).str.lower()
    df["is_upcoming"] = t.str.contains("upcoming|planned|proposed|future|construction")
    df["current_type"] = np.where(t.str.contains(r"\bdc\b|fast|rapid"), "DC",
                                  np.where(t.str.contains(r"\bac\b|destination"), "AC", "Unknown"))
    unknown_before = int((df["current_type"] == "Unknown").sum())     
    rt = df["charger_rating"].fillna("").str.strip().str.upper()
    unk = df["current_type"] == "Unknown"
    df.loc[unk & (rt == "AC"), "current_type"] = "AC"                
    df.loc[unk & (rt == "DC"), "current_type"] = "DC"
    infer = (df["current_type"] == "Unknown") & df["rating_kw"].notna()   
    df.loc[infer, "current_type"] = np.where(df.loc[infer, "rating_kw"] > 22, "DC", "AC")
    st["type_inferred_when_missing"] = unknown_before - int((df["current_type"] == "Unknown").sum())
    df["is_dc_fast"] = (df["current_type"] == "DC") & ~df["is_upcoming"]   # existing DC chargers only

    # rating_kw: fill remaining gaps with a flat default by current type
    missing_rating_before = int(df["rating_kw"].isna().sum())
    default_ratings = pd.Series(np.where(df["current_type"] == "DC", 50.0, 22.0), index=df.index)
    df["rating_kw"] = df["rating_kw"].fillna(default_ratings)
    st["rating_kw_imputed"] = missing_rating_before - int(df["rating_kw"].isna().sum())

    #  names: one spelling per operator / case fixes
    op = df["operator"].fillna("Unknown")
    st["operators_raw"] = int(op.nunique())
    for pat, name in OPERATOR_RULES:
        op = op.mask(op.str.lower().str.contains(pat, regex=True), name)
    key = op.str.lower().str.replace(r"[^a-z0-9]+", "", regex=True)
    df["operator"] = key.map(op.groupby(key).agg(lambda s: s.value_counts().index[0]))
    st["operators_clean"] = int(df["operator"].nunique())
    for c in ("station_name", "station_address", "lga_name"):
        df[c] = df[c].map(lambda s: s.title() if isinstance(s, str) and (s.isupper() or s.islower()) else s)

    # station_name: flag then fill gaps - street from the address, else operator + LGA/postcode
    df["is_station_name_imputed"] = df["station_name"].isna()
    st["station_names_imputed"] = int(df["is_station_name_imputed"].sum())
    street_fallback = df["station_address"].fillna("").str.split(
        r",|\bNSW\b|\b\d{4}\b", n=1, regex=True).str[0].str.strip()
    loc_detail = df["lga_name"].fillna(df["postcode"].fillna("Site"))
    secondary_fallback = df["operator"].fillna("EV") + " Charger (" + loc_detail + ")"
    fallback_name = street_fallback.where(street_fallback.str.len() > 3, secondary_fallback)
    df["station_name"] = df["station_name"].fillna(fallback_name)
    df["station_name_key"] = df["station_name"].str.lower().str.replace(r"[^a-z0-9]+", "", regex=True)

    # coordinates: repair obvious slips, then drop what cannot be located in NSW
    sw = df["latitude"].between(140, 155) & df["longitude"].between(-38, -27)          # lat/lon swapped
    df.loc[sw, ["latitude", "longitude"]] = df.loc[sw, ["longitude", "latitude"]].to_numpy()
    neg = df["latitude"].between(27, 38)                                                # minus sign lost
    df.loc[neg, "latitude"] *= -1
    st["coordinates_repaired"] = int(sw.sum() + neg.sum())
    missing = df["latitude"].isna() | df["longitude"].isna()
    outside = ~missing & ~(df["latitude"].between(*NSW["lat"]) & df["longitude"].between(*NSW["lon"]))
    st["dropped_missing_coordinates"], st["dropped_outside_nsw_extent"] = int(missing.sum()), int(outside.sum())
    df = df[~(missing | outside)]

    # duplicates (compared after cleaning, so spacing/case variants are caught)
    dup_cols = ["operator", "station_name_key", "number_of_plugs", "current_type", "rating_kw",
                "is_upcoming", "latitude", "longitude"]
    dups = df.duplicated(subset=dup_cols, keep="first")
    st["duplicates_removed"] = int(dups.sum())
    df = df[~dups].copy()

    # ids + output
    df["site_id"] = df.groupby(["operator", df["latitude"].round(4), df["longitude"].round(4)]).ngroup() + 1
    df = df.sort_values("source_row").reset_index(drop=True)
    df.insert(0, "charger_id", np.arange(1, len(df) + 1))
    cols = ["charger_id", "site_id", "station_name", "station_name_key", "is_station_name_imputed",
            "station_address", "operator", "number_of_plugs", "charger_type", "current_type", "is_dc_fast",
            "is_upcoming", "charger_rating", "rating_kw", "latitude", "longitude", "lga_name", "postcode",
            "source", "source_row"]
    st["null_counts"] = df[EXPECTED].isna().sum().to_dict()
    st.update(clean_rows=len(df), dc_fast_rows=int(df["is_dc_fast"].sum()), sites=int(df["site_id"].nunique()))
    return df[cols], st

def preprocess() -> pd.DataFrame:
    cfg.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df, st = clean(load_raw())
    df.to_csv(cfg.EV_CLEAN_CSV, index=False)
    log.info("cleaned %d of %d rows -> %s", st["clean_rows"], st["raw_rows"], cfg.EV_CLEAN_CSV)
    return df


# ENTRY POINT
def run(force: bool = False, clean_only: bool = False) -> pd.DataFrame:
    if not clean_only:
        acquire(force)
    return preprocess()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Download and clean the NSW EV charger data.")
    ap.add_argument("--force", action="store_true", help="re-download raw data")
    ap.add_argument("--clean-only", action="store_true", help="skip downloading; clean data/raw/ as is")
    args = ap.parse_args()
    try:
        run(force=args.force, clean_only=args.clean_only)
    except Exception as exc:
        log.error("FAILED: %s", exc)
        sys.exit(1)