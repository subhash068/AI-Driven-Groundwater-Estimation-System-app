from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ZIP = ROOT / "data" / "raw" / "GTWells_Krishna.zip"
STAGING = ROOT / ".tmp_gtwells_export"
OUTPUT_JSON = ROOT / "frontend" / "public" / "data" / "wells_krishna.json"


def norm_text(value) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.replace("\n", " ").split()).strip()


def safe_float(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return float(numeric)


def dominant_value(series: pd.Series, default: str = "Unknown") -> str:
    values = series.dropna().astype(str).map(norm_text)
    values = values[values != ""]
    if values.empty:
        return default
    mode = values.mode()
    return str(mode.iloc[0]) if not mode.empty else str(values.iloc[0])


def main() -> None:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(SOURCE_ZIP) as archive:
        archive.extractall(STAGING)

    shp_candidates = list(STAGING.rglob("kris.shp"))
    if not shp_candidates:
        raise FileNotFoundError("Could not find kris.shp inside GTWells_Krishna.zip")

    wells = gpd.read_file(shp_candidates[0])
    if wells.crs is None:
        wells = wells.set_crs("EPSG:4326", allow_override=True)

    for col in ["District_N", "Mandal_Nam", "Village_Na", "Bore_Well", "Well_Type", "Irrigation"]:
        if col in wells.columns:
            wells[col] = wells[col].fillna("").astype(str).map(norm_text)

    for col in ["Bore_Depth", "Pump_Capac", "Lat", "Long"]:
        if col in wells.columns:
            wells[col] = pd.to_numeric(wells[col], errors="coerce")

    wells = wells[
        [
            "District_N",
            "Mandal_Nam",
            "Village_Na",
            "Bore_Well",
            "Well_Type",
            "Bore_Depth",
            "Pump_Capac",
            "Irrigation",
            "Lat",
            "Long",
            "geometry",
        ]
    ].copy()

    grouped = (
        wells.groupby(["District_N", "Mandal_Nam", "Village_Na"], dropna=False)
        .agg(
            well_count=("Bore_Well", "count"),
            working_count=("Bore_Well", lambda s: int((s.astype(str).str.lower() == "working").sum())),
            dominant_well_type=("Well_Type", dominant_value),
            dominant_irrigation=("Irrigation", dominant_value),
            avg_bore_depth_m=("Bore_Depth", "mean"),
            avg_pump_capacity_hp=("Pump_Capac", "mean"),
            latitude=("Lat", "mean"),
            longitude=("Long", "mean"),
        )
        .reset_index()
    )

    grouped["avg_bore_depth_m"] = grouped["avg_bore_depth_m"].fillna(0).round(2)
    grouped["avg_pump_capacity_hp"] = grouped["avg_pump_capacity_hp"].fillna(0).round(2)
    grouped["latitude"] = grouped["latitude"].fillna(0).round(6)
    grouped["longitude"] = grouped["longitude"].fillna(0).round(6)
    grouped["working_pct"] = grouped.apply(
        lambda row: round((row["working_count"] / row["well_count"] * 100.0) if row["well_count"] else 0.0, 2),
        axis=1,
    )

    features = []
    for _, row in grouped.iterrows():
        lat = safe_float(row.get("latitude"))
        lon = safe_float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "district": row.get("District_N") or "KRISHNA",
                    "mandal": row.get("Mandal_Nam") or "Unknown",
                    "village": row.get("Village_Na") or "Unknown",
                    "well_count": int(row.get("well_count") or 0),
                    "working_count": int(row.get("working_count") or 0),
                    "working_pct": float(row.get("working_pct") or 0),
                    "dominant_well_type": row.get("dominant_well_type") or "Unknown",
                    "dominant_irrigation": row.get("dominant_irrigation") or "Unknown",
                    "avg_bore_depth_m": float(row.get("avg_bore_depth_m") or 0),
                    "avg_pump_capacity_hp": float(row.get("avg_pump_capacity_hp") or 0),
                    "latitude": lat,
                    "longitude": lon,
                },
            }
        )

    payload = {
        "generated_from": "GTWells_Krishna.zip",
        "district": "KRISHNA",
        "villageCount": len(features),
        "totalWells": int(len(wells)),
        "features": features,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if STAGING.exists():
        shutil.rmtree(STAGING)


if __name__ == "__main__":
    main()
