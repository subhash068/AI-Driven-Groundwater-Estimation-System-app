from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE_XLSX = ROOT / "data" / "raw" / "PzWaterLevel_2024.xlsx"
OUTPUT_JSON = ROOT / "frontend" / "public" / "data" / "krishna_piezometers.json"


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).replace("\n", " ").strip() for column in frame.columns]
    return frame


def safe_float(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


def main() -> None:
    df = normalize_columns(pd.read_excel(SOURCE_XLSX, sheet_name="meta-historical"))
    df["District"] = df["District"].astype(str).str.strip().str.upper()
    krishna = df[df["District"] == "KRISHNA"].copy()

    date_columns = [column for column in krishna.columns if str(column).startswith("2024-")]
    stations = []
    for _, row in krishna.iterrows():
        monthly = []
        for column in date_columns:
            value = safe_float(row.get(column))
            if value is None:
                continue
            monthly.append({"label": str(column)[:7], "value": round(value, 2)})

        latest_reading = monthly[-1] if monthly else None
        latitude = safe_float(row.get("Latitude  (Decimal Degrees)"))
        longitude = safe_float(row.get("Longitude  (Decimal Degrees)"))
        if latitude is None or longitude is None:
            continue

        stations.append(
            {
                "id": str(row.get("ID")).strip() if pd.notna(row.get("ID")) else None,
                "district": row.get("District"),
                "mandal": str(row.get("Mandal Name") or "").strip(),
                "village": str(row.get("Village Name") or "").strip(),
                "location": str(row.get("Location (Premises)") or "").strip(),
                "project": str(row.get("Project") or "").strip(),
                "principalAquifer": str(row.get("Principal Aquifer") or "").strip(),
                "totalDepthM": safe_float(row.get("Total  Depth  in m")),
                "mslM": safe_float(row.get("MSL in meters")),
                "latitude": latitude,
                "longitude": longitude,
                "monthlyReadings2024": monthly,
                "latestReading2024": latest_reading,
            }
        )

    payload = {
        "generated_from": SOURCE_XLSX.name,
        "district": "KRISHNA",
        "stationCount": len(stations),
        "stations": stations,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
