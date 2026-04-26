from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL_DATASET = ROOT / "frontend" / "public" / "data" / "final_dataset.json"
MAP_DATA = ROOT / "frontend" / "public" / "data" / "map_data_predictions.geojson"
OUTPUT_JSON = ROOT / "frontend" / "public" / "data" / "anomalies_krishna.json"


def to_number(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def classify_anomaly(deviation: float) -> str:
    if deviation >= 2.0:
        return "Severe drop"
    if deviation >= 0.75:
        return "Moderate drop"
    if deviation <= -0.75:
        return "Rise"
    return "Normal"


def main() -> None:
    final_rows = json.loads(FINAL_DATASET.read_text(encoding="utf-8"))
    map_data = json.loads(MAP_DATA.read_text(encoding="utf-8"))

    geometry_by_id = {}
    for feature in map_data.get("features", []):
        props = feature.get("properties", {})
        village_id = props.get("village_id") or props.get("Village_ID")
        if village_id is None:
            continue
        geometry_by_id[int(village_id)] = feature.get("geometry")

    features = []
    for row in final_rows:
        village_id = int(row.get("Village_ID") or row.get("village_id") or 0)
        geometry = geometry_by_id.get(village_id)
        if not geometry:
            continue

        current = to_number(row.get("actual_last_month") or row.get("GW_Level"))
        long_term_avg = to_number(row.get("long_term_avg"))
        trend_slope = to_number(row.get("trend_slope"))
        if current is None or long_term_avg is None:
            continue

        deviation = round(current - long_term_avg, 4)
        anomaly_type = classify_anomaly(deviation)
        anomaly_score = round(abs(deviation), 4)

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "village_id": village_id,
                    "village_name": row.get("Village_Name") or row.get("village_name") or "Unknown",
                    "district": row.get("District") or row.get("district") or "KRISHNA",
                    "mandal": row.get("Mandal") or row.get("mandal") or "Unknown",
                    "anomaly_type": anomaly_type,
                    "anomaly_score": anomaly_score,
                    "deviation_m": deviation,
                    "current_groundwater_m": round(current, 4),
                    "long_term_avg_m": round(long_term_avg, 4),
                    "trend_slope": round(trend_slope, 6) if trend_slope is not None else None,
                    "detected_at": "2024-12-01",
                },
            }
        )

    payload = {
        "generated_from": "final_dataset.json + map_data_predictions.geojson",
        "district": "KRISHNA",
        "featureCount": len(features),
        "features": features,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
