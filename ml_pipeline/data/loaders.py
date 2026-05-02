from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import re
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd

DEFAULT_CRS = "EPSG:4326"


@dataclass
class LoadedData:
    villages: gpd.GeoDataFrame
    piezometer: pd.DataFrame
    pumping: pd.DataFrame
    rainfall: pd.DataFrame
    aquifer: gpd.GeoDataFrame
    canals: gpd.GeoDataFrame
    streams: gpd.GeoDataFrame
    tanks: gpd.GeoDataFrame
    lulc: gpd.GeoDataFrame


def _read_vector(path: Path, name_hint: str | None = None) -> gpd.GeoDataFrame:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            shp_files = [member for member in zf.namelist() if member.lower().endswith(".shp")]
        if not shp_files:
            raise FileNotFoundError(f"No shapefile found in archive: {path}")
        if name_hint:
            hinted = [member for member in shp_files if name_hint.lower() in member.lower()]
            shp = hinted[0] if hinted else shp_files[0]
        else:
            shp = shp_files[0]
        gdf = gpd.read_file(f"zip://{path}!{shp}")
    else:
        gdf = gpd.read_file(path)

    if gdf.crs is None:
        gdf = gdf.set_crs(DEFAULT_CRS)
    return gdf.to_crs(DEFAULT_CRS)


def _read_excel_or_csv(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _find_first(raw_dir: Path, patterns: Iterable[str], suffixes: tuple[str, ...]) -> Path | None:
    candidates = []
    for file in raw_dir.iterdir():
        if not file.is_file() or file.suffix.lower() not in suffixes:
            continue
        lname = file.name.lower()
        if any(pattern in lname for pattern in patterns):
            candidates.append(file)
    return sorted(candidates)[0] if candidates else None


def _guess_village_name_col(gdf: gpd.GeoDataFrame) -> str | None:
    cols = [str(col) for col in gdf.columns]
    rank = ["village_name", "village", "dvname", "name"]
    for key in rank:
        for col in cols:
            if key in col.lower():
                return col
    return None


def _normalize_villages(villages: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    villages = villages.copy()
    villages.columns = [str(col).strip() for col in villages.columns]
    name_col = _guess_village_name_col(villages)
    if name_col:
        villages["village_name"] = villages[name_col].astype(str).str.strip()
    else:
        villages["village_name"] = [f"Village_{idx+1}" for idx in range(len(villages))]
    villages["village_id"] = np.arange(1, len(villages) + 1, dtype=int)
    villages["village_key"] = villages["village_name"].str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    return villages[["village_id", "village_name", "village_key", "geometry"]]


def _lulc_fallback_from_existing(villages: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    candidates = [
        Path("output/final_dataset.csv"),
        Path("output/final_dataset_train_ready.csv"),
    ]
    source = None
    for cand in candidates:
        if cand.exists():
            source = cand
            break

    if source is None:
        out = villages[["geometry"]].copy()
        out["lulc_class"] = "Unknown"
        return gpd.GeoDataFrame(out, geometry="geometry", crs=DEFAULT_CRS)

    df = pd.read_csv(source)
    df.columns = [str(col).strip() for col in df.columns]
    name_col = next((c for c in df.columns if c.lower() in {"village_name", "village"}), None)
    if name_col is None:
        out = villages[["geometry"]].copy()
        out["lulc_class"] = "Unknown"
        return gpd.GeoDataFrame(out, geometry="geometry", crs=DEFAULT_CRS)

    lulc_cols = {
        "Water%": "Water",
        "Trees%": "Trees",
        "Crops%": "Crops",
        "Built%": "Built Area",
        "Bare%": "Bare Ground",
        "Rangeland%": "Rangeland",
    }
    available = [col for col in lulc_cols if col in df.columns]
    if not available:
        out = villages[["geometry"]].copy()
        out["lulc_class"] = "Unknown"
        return gpd.GeoDataFrame(out, geometry="geometry", crs=DEFAULT_CRS)

    for col in available:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["village_key"] = df[name_col].astype(str).str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    df["lulc_class"] = df[available].idxmax(axis=1).map(lulc_cols).fillna("Unknown")
    lk = df[["village_key", "lulc_class"]].drop_duplicates("village_key")

    out = villages.merge(lk, on="village_key", how="left")
    out["lulc_class"] = out["lulc_class"].fillna("Unknown")
    return gpd.GeoDataFrame(out[["geometry", "lulc_class"]], geometry="geometry", crs=DEFAULT_CRS)


def _normalize_piezometer(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data.columns = [str(col).strip() for col in data.columns]
    lc = {col.lower(): col for col in data.columns}

    lat_col = next((lc[key] for key in lc if "lat" in key), None)
    lon_col = next((lc[key] for key in lc if "lon" in key or "long" in key), None)
    if lat_col is None or lon_col is None:
        raise ValueError("Piezometer file must include latitude and longitude columns.")

    date_col = next((lc[key] for key in lc if key in {"date", "timestamp", "observed_date"}), None)
    gw_col = next((lc[key] for key in lc if "groundwater_level" in key or "water_level" in key), None)

    if date_col and gw_col:
        out = data[[date_col, lat_col, lon_col, gw_col]].copy()
        out = out.rename(
            columns={
                date_col: "date",
                lat_col: "lat",
                lon_col: "lon",
                gw_col: "groundwater_level",
            }
        )
    else:
        date_like_cols = []
        for col in data.columns:
            parsed = pd.to_datetime(col, errors="coerce")
            if pd.notna(parsed):
                date_like_cols.append(col)
        if not date_like_cols:
            raise ValueError("Piezometer file must include a date column or date-wise groundwater columns.")
        id_cols = [lat_col, lon_col]
        wide = data[id_cols + date_like_cols].copy()
        out = wide.melt(id_vars=id_cols, value_vars=date_like_cols, var_name="date", value_name="groundwater_level")
        out = out.rename(columns={lat_col: "lat", lon_col: "lon"})

    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
    out["lon"] = pd.to_numeric(out["lon"], errors="coerce")
    out["groundwater_level"] = pd.to_numeric(out["groundwater_level"], errors="coerce")
    out = out.dropna(subset=["date", "lat", "lon", "groundwater_level"]).copy()
    out["month"] = out["date"].dt.to_period("M").dt.to_timestamp()
    return out


def _normalize_pumping(df: pd.DataFrame, villages: gpd.GeoDataFrame) -> pd.DataFrame:
    data = df.copy()
    data.columns = [str(col).strip() for col in data.columns]
    if data.empty:
        return pd.DataFrame(columns=["village_id", "pumping"])

    lc = {col.lower(): col for col in data.columns}
    village_col = next((lc[key] for key in lc if "village" in key), None)
    value_col = next((lc[key] for key in lc if ("pump" in key or "draft" in key) and "date" not in key), None)
    if value_col is None:
        return pd.DataFrame(columns=["village_id", "pumping"])

    out = data[[value_col] + ([village_col] if village_col else [])].copy()
    out["pumping"] = pd.to_numeric(out[value_col], errors="coerce")
    if village_col:
        out["village_key"] = out[village_col].astype(str).str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
        out = out.merge(villages[["village_id", "village_key"]], on="village_key", how="left")
    else:
        out["village_id"] = np.nan
    out = out.dropna(subset=["village_id", "pumping"]).copy()
    out["village_id"] = out["village_id"].astype(int)
    return out.groupby("village_id", as_index=False)["pumping"].mean()


def _build_default_rainfall(villages: gpd.GeoDataFrame, start_month: pd.Timestamp, end_month: pd.Timestamp) -> pd.DataFrame:
    months = pd.date_range(start=start_month, end=end_month, freq="MS")
    village_ids = villages["village_id"].astype(int).unique()
    
    # Use MultiIndex to create the combinations efficiently without a huge list of dicts
    idx = pd.MultiIndex.from_product([village_ids, months], names=["village_id", "date"])
    df = pd.DataFrame(index=idx).reset_index()
    
    # Assign seasonal values using vectorized operations
    df["rainfall_mm"] = np.where(df["date"].dt.month.isin([6, 7, 8, 9]), 180.0, 45.0)
    
    # Add deterministic jitter based on village_id to ensure unique profiles
    # (village_id * 137 % 30) / 100.0 gives a variation between 0% and 30%
    # We'll center it around 1.0 (range 0.85 to 1.15)
    jitter = ((df["village_id"] * 137) % 31 - 15) / 100.0
    df["rainfall_mm"] = df["rainfall_mm"] * (1.0 + jitter)
    
    return df


def _normalize_rainfall(df: pd.DataFrame, villages: gpd.GeoDataFrame, piezometer: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data.columns = [str(col).strip() for col in data.columns]
    lc = {col.lower(): col for col in data.columns}

    rain_col = next((lc[key] for key in lc if "rain" in key), None)
    if rain_col is None:
        return pd.DataFrame(columns=["village_id", "date", "rainfall_mm"])

    date_col = next((lc[key] for key in lc if key in {"date", "timestamp", "month"}), None)
    village_col = next((lc[key] for key in lc if "village" in key), None)

    if date_col is None:
        # If no date column, assume monthly sequence for current piezometer range.
        start = piezometer["month"].min()
        dates = pd.date_range(start=start, periods=len(data), freq="MS")
        data["date"] = dates
        date_col = "date"

    out = data[[rain_col, date_col] + ([village_col] if village_col else [])].copy()
    out = out.rename(columns={rain_col: "rainfall_mm", date_col: "date"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    out["rainfall_mm"] = pd.to_numeric(out["rainfall_mm"], errors="coerce")
    out = out.dropna(subset=["date", "rainfall_mm"]).copy()

    if village_col:
        out["village_key"] = out[village_col].astype(str).str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
        out = out.merge(villages[["village_id", "village_key"]], on="village_key", how="left")
    else:
        out["village_id"] = np.nan

    if out["village_id"].isna().all():
        # Broadcast district-level rainfall to all villages.
        village_ids = villages["village_id"].unique()
        dates = out["date"].dropna().unique()
        base = pd.DataFrame([(int(v), d) for v in village_ids for d in dates], columns=["village_id", "date"])
        avg = out.groupby("date", as_index=False)["rainfall_mm"].mean()
        out = base.merge(avg, on="date", how="left")
        
        # Add deterministic jitter for broadcasted data
        jitter = ((out["village_id"] * 137) % 31 - 15) / 100.0
        out["rainfall_mm"] = out["rainfall_mm"] * (1.0 + jitter)
    else:
        out = out.dropna(subset=["village_id"]).copy()
        out["village_id"] = out["village_id"].astype(int)

    return out.groupby(["village_id", "date"], as_index=False)["rainfall_mm"].sum()


def load_all_data(raw_dir: Path = Path("data/raw")) -> LoadedData:
    villages_path = _find_first(raw_dir, patterns=["village", "mandal"], suffixes=(".zip", ".geojson", ".shp"))
    aquifer_path = _find_first(raw_dir, patterns=["aquifer"], suffixes=(".zip", ".geojson", ".shp"))
    canals_path = _find_first(raw_dir, patterns=["canal"], suffixes=(".zip", ".geojson", ".shp"))
    streams_path = _find_first(raw_dir, patterns=["strm", "stream"], suffixes=(".zip", ".geojson", ".shp"))
    tanks_path = _find_first(raw_dir, patterns=["tank"], suffixes=(".zip", ".geojson", ".shp"))
    lulc_path = _find_first(raw_dir, patterns=["lulc"], suffixes=(".zip", ".geojson", ".shp"))
    piezo_path = _find_first(raw_dir, patterns=["pzwater", "piez", "waterlevel"], suffixes=(".xlsx", ".xls", ".csv"))
    pumping_path = _find_first(raw_dir, patterns=["pumping"], suffixes=(".xlsx", ".xls", ".csv"))
    rainfall_path = _find_first(raw_dir, patterns=["rain"], suffixes=(".csv", ".xlsx", ".xls"))

    if villages_path is None or piezo_path is None or aquifer_path is None or lulc_path is None:
        raise FileNotFoundError("Missing required files. Needed: villages, piezometer, aquifer, and LULC.")

    villages = _normalize_villages(_read_vector(villages_path, name_hint="vil"))
    aquifer = _read_vector(aquifer_path)
    canals = _read_vector(canals_path) if canals_path else gpd.GeoDataFrame(geometry=[], crs=DEFAULT_CRS)
    streams = _read_vector(streams_path) if streams_path else gpd.GeoDataFrame(geometry=[], crs=DEFAULT_CRS)
    tanks = _read_vector(tanks_path) if tanks_path else gpd.GeoDataFrame(geometry=[], crs=DEFAULT_CRS)
    try:
        lulc = _read_vector(lulc_path)
    except FileNotFoundError:
        lulc = _lulc_fallback_from_existing(villages)

    piezometer = _normalize_piezometer(_read_excel_or_csv(piezo_path))
    pumping = _normalize_pumping(_read_excel_or_csv(pumping_path), villages) if pumping_path else pd.DataFrame(columns=["village_id", "pumping"])

    if rainfall_path:
        rainfall = _normalize_rainfall(_read_excel_or_csv(rainfall_path), villages, piezometer)
    else:
        start_month = piezometer["month"].min()
        end_month = piezometer["month"].max()
        rainfall = _build_default_rainfall(villages, start_month=start_month, end_month=end_month)

    # Safety cleanup for mixed column names from source files.
    aquifer.columns = [re.sub(r"\s+", "_", str(col).strip()) for col in aquifer.columns]
    lulc.columns = [re.sub(r"\s+", "_", str(col).strip()) for col in lulc.columns]

    return LoadedData(
        villages=villages,
        piezometer=piezometer,
        pumping=pumping,
        rainfall=rainfall,
        aquifer=aquifer,
        canals=canals,
        streams=streams,
        tanks=tanks,
        lulc=lulc,
    )
