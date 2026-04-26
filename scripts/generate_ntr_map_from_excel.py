from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
FRONTEND_DATA = ROOT / "frontend" / "public" / "data"

TARGET_DISTRICT = "NTR"

def canonical_name(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text)


def canonical_district(value: object) -> str:
    text = canonical_name(value).upper()
    collapsed = re.sub(r"[^A-Z0-9]+", "", text)
    if collapsed in {"NTR", "NTRDISTRICT", "NTRDIST", "NTRDT"}:
        return "NTR"
    return text


def norm_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\(.*?\)", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def monthly_columns(columns: list[object]) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    for col in columns:
        if isinstance(col, pd.Timestamp):
            out.append(col)
        elif hasattr(col, "year") and hasattr(col, "month"):
            out.append(pd.Timestamp(col))
    return sorted(out)


def build_pumping_lookup() -> dict[tuple[str, str, str], dict[str, float]]:
    pump = pd.read_excel(RAW / "Pumping Data.xlsx", sheet_name="Sheet1", header=1)
    pump.columns = [str(c).strip() for c in pump.columns]
    pump = pump.rename(
        columns={
            "Unnamed: 0": "district",
            "Unnamed: 1": "mandal",
            "Unnamed: 2": "village",
            "Unnamed: 4": "functioning_wells",
            "Monsoon": "monsoon_draft_ha_m",
            "Non-Monsoon": "non_monsoon_draft_ha_m",
        }
    )
    for col in ["district", "mandal", "village"]:
        pump[col] = pump[col].fillna("").map(canonical_name)
    pump["district"] = pump["district"].map(canonical_district)
    pump = pump[pump["district"] == TARGET_DISTRICT].copy()

    pump["functioning_wells"] = pd.to_numeric(pump.get("functioning_wells"), errors="coerce").fillna(0.0)
    pump["monsoon_draft_ha_m"] = pd.to_numeric(pump.get("monsoon_draft_ha_m"), errors="coerce").fillna(0.0)
    pump["non_monsoon_draft_ha_m"] = pd.to_numeric(pump.get("non_monsoon_draft_ha_m"), errors="coerce").fillna(0.0)

    grouped = (
        pump.groupby(
            [
                pump["district"].map(norm_text),
                pump["mandal"].map(norm_text),
                pump["village"].map(norm_text),
            ],
            dropna=False,
        )
        .agg(
            pumping_functioning_wells=("functioning_wells", "sum"),
            pumping_estimated_draft_ha_m=("monsoon_draft_ha_m", "mean"),
        )
        .reset_index()
    )

    lookup: dict[tuple[str, str, str], dict[str, float]] = {}
    for _, row in grouped.iterrows():
        key = (str(row.iloc[0]), str(row.iloc[1]), str(row.iloc[2]))
        lookup[key] = {
            "pumping_functioning_wells": float(row["pumping_functioning_wells"]),
            "pumping_estimated_draft_ha_m": float(row["pumping_estimated_draft_ha_m"]),
        }
    return lookup


def compute_trend(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    series = pd.Series(values, dtype=float)
    x = pd.Series(range(len(series)), dtype=float)
    slope = x.cov(series) / x.var() if x.var() else 0.0
    return round(float(slope), 6)


def main() -> None:
    FRONTEND_DATA.mkdir(parents=True, exist_ok=True)
    pumping_lookup = build_pumping_lookup()

    pz = pd.read_excel(RAW / "PzWaterLevel_2024.xlsx", sheet_name="meta-historical")
    month_cols = monthly_columns(list(pz.columns))
    month_labels = [pd.Timestamp(c).strftime("%Y-%m") for c in month_cols]

    pz["district"] = pz["District"].map(canonical_district)
    pz["mandal"] = pz["Mandal Name"].map(canonical_name)
    pz["village_name"] = pz["Village Name"].map(canonical_name)
    pz["lat"] = pd.to_numeric(pz["Latitude \n(Decimal Degrees)"], errors="coerce")
    pz["lon"] = pd.to_numeric(pz["Longitude \n(Decimal Degrees)"], errors="coerce")
    pz = pz[(pz["district"] == TARGET_DISTRICT) & pz["lat"].notna() & pz["lon"].notna()].copy()

    for col in month_cols:
        pz[col] = pd.to_numeric(pz[col], errors="coerce")

    features = []
    rows = []
    stations = []
    village_id = 200000

    grouped = pz.groupby(
        [
            pz["district"].map(norm_text),
            pz["mandal"].map(norm_text),
            pz["village_name"].map(norm_text),
        ],
        dropna=False,
    )

    for _, g in grouped:
        sample = g.iloc[0]
        district = canonical_district(sample["district"])
        mandal = canonical_name(sample["mandal"]).upper()
        village_name = canonical_name(sample["village_name"])
        lat = float(g["lat"].mean())
        lon = float(g["lon"].mean())

        mean_series = g[month_cols].mean(axis=0, skipna=True)
        full_values = [None if pd.isna(v) else round(float(v), 4) for v in mean_series.tolist()]
        tail_values = full_values[-24:]
        finite_tail = [v for v in tail_values if v is not None]
        depth = round(float(finite_tail[-1]), 2) if finite_tail else None
        trend = compute_trend([float(v) for v in full_values if v is not None])

        key = (norm_text(district), norm_text(mandal), norm_text(village_name))
        pumping = pumping_lookup.get(key, {})
        risk_level = "safe"
        if depth is not None:
            if depth >= 30:
                risk_level = "high"
            elif depth >= 20:
                risk_level = "medium"

        props = {
            "village_id": village_id,
            "village_name": village_name,
            "district": district,
            "mandal": mandal,
            "state": "Andhra Pradesh",
            "depth": depth,
            "monthly_depths": tail_values,
            "monthly_depths_dates": month_labels[-24:],
            "monthly_depths_full": full_values,
            "monthly_depths_full_dates": month_labels,
            "available_years": sorted({int(label[:4]) for label in month_labels}),
            "obs_station_count": int(len(g)),
            "actual_last_month": depth,
            "target_last_month": depth,
            "trend_slope": trend,
            "long_term_avg": round(float(sum(finite_tail) / len(finite_tail)), 4) if finite_tail else None,
            "seasonal_variation": None,
            "centroid_lat": lat,
            "centroid_lon": lon,
            "pumping_functioning_wells": float(pumping.get("pumping_functioning_wells", 0.0)),
            "pumping_estimated_draft_ha_m": float(pumping.get("pumping_estimated_draft_ha_m", 0.0)),
            "wells_total": 0.0,
            "wells_working_pct": 0.0,
            "avg_bore_depth_m": 0.0,
            "avg_pump_capacity_hp": 0.0,
            "dominant_irrigation": "Unknown",
            "weathered_rock": 12,
            "fractured_rock": 18,
            "aquifer_code": "NA",
            "aquifer_class": "Unknown",
            "geomorphology": "Unknown",
            "lulc_2011_dominant": "unclassified",
            "lulc_2021_dominant": "unclassified",
            "lulc_change": "stable",
            "risk_level": risk_level,
        }

        feature = {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
        }
        features.append(feature)
        rows.append(props)

        stations.append(
            {
                "id": str(sample.get("ID", village_id)),
                "district": district,
                "mandal": mandal,
                "village": village_name,
                "location": canonical_name(sample.get("Location\n(Premises)", "")),
                "project": canonical_name(sample.get("Project", "")),
                "principalAquifer": canonical_name(sample.get("Principal Aquifer", "Unknown")),
                "totalDepthM": float(pd.to_numeric(sample.get("Total \nDepth \nin m"), errors="coerce") or 0.0),
                "mslM": float(pd.to_numeric(sample.get("MSL in meters"), errors="coerce") or 0.0),
                "latitude": lat,
                "longitude": lon,
                "latestReading2024": {
                    "label": month_labels[-1] if month_labels else "2024",
                    "value": depth,
                },
                "monthlyReadings2024": [
                    {"label": label, "value": val}
                    for label, val in zip(month_labels[-12:], full_values[-12:], strict=False)
                    if val is not None
                ],
            }
        )
        village_id += 1

    geojson = {"type": "FeatureCollection", "features": features}

    (FRONTEND_DATA / "village_boundaries_ntr.geojson").write_text(json.dumps(geojson), encoding="utf-8")
    (FRONTEND_DATA / "villages_ntr.geojson").write_text(json.dumps(geojson), encoding="utf-8")
    (FRONTEND_DATA / "final_dataset_ntr.json").write_text(json.dumps(rows), encoding="utf-8")
    (FRONTEND_DATA / "ntr_piezometers.json").write_text(
        json.dumps({"source": "PzWaterLevel_2024.xlsx", "stations": stations}),
        encoding="utf-8",
    )

    print(f"Generated NTR map-ready rows: {len(rows)}")


if __name__ == "__main__":
    main()
