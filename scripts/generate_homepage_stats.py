import csv
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "output" / "final_dataset.csv"
NTR_DATASET_PATH = ROOT / "frontend" / "public" / "data" / "final_dataset_ntr.json"
METRICS_PATH = ROOT / "model" / "artifacts" / "metrics.json"
OUTPUT_PATH = ROOT / "frontend" / "public" / "data" / "homepage_stats.json"
SOURCE_COVERAGE_PATH = ROOT / "frontend" / "public" / "data" / "source_excel_coverage.json"
HIGH_RISK_THRESHOLD = 60.0
EXCLUDED_DISTRICTS = set()


def _to_float(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _mean(values):
    if not values:
        return None
    return sum(values) / len(values)

def _trend_arrow(value):
    if value is None:
        return "NA"
    if value >= 0.03:
        return "↓↓"
    if value > 0:
        return "↓"
    return "↔"


def _load_metrics():
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _load_source_coverage():
    if not SOURCE_COVERAGE_PATH.exists():
        return None
    try:
        data = json.loads(SOURCE_COVERAGE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _build_snapshot(rows):
    for row in rows:
        actual = _to_float(row.get("actual_last_month"))
        predicted = _to_float(row.get("target_last_month"))
        if actual is None:
            continue
        if predicted is None:
            predicted = _to_float(row.get("depth"))
        if predicted is None:
            continue
        return {
            "sample_village": row.get("village_name") or "Unknown",
            "actual_last_month": round(actual, 3),
            "predicted_gwl": round(predicted, 3)
        }
    return {
        "sample_village": "Unknown",
        "actual_last_month": None,
        "predicted_gwl": None
    }


def _build_district_aggregation(rows, source_coverage):
    grouped = {}
    for row in rows:
        district = str((row.get("district") or "Unknown")).strip().upper() or "UNKNOWN"
        grouped.setdefault(district, []).append(row)

    ordered_districts = []
    if isinstance(source_coverage, dict):
        ordered_districts = [
            str(item).strip().upper()
            for item in (source_coverage.get("districts") or [])
            if str(item).strip()
        ]
    for district in sorted(grouped.keys()):
        if district not in ordered_districts:
            ordered_districts.append(district)

    aggregation = []
    for district in ordered_districts:
        district_rows = grouped.get(district, [])
        trend_values = []
        gw_levels = []
        high_risk_count = 0

        for row in district_rows:
            trend = _to_float(row.get("trend_slope"))
            if trend is not None:
                trend_values.append(trend)

            level = _to_float(row.get("actual_last_month"))
            if level is None:
                level = _to_float(row.get("target_last_month"))
            if level is None:
                level = _to_float(row.get("depth"))
            if level is not None:
                gw_levels.append(level)

            risk_score = _to_float(row.get("risk_score"))
            if risk_score is not None and risk_score >= HIGH_RISK_THRESHOLD:
                high_risk_count += 1

        avg_trend = _mean(trend_values)
        aggregation.append({
            "district": district,
            "villages": len(district_rows) if district_rows else None,
            "avg_groundwater_level": round(_mean(gw_levels), 3) if gw_levels else None,
            "avg_trend_slope": round(avg_trend, 4) if avg_trend is not None else None,
            "high_risk_count": high_risk_count if district_rows else None,
            "trend_arrow": _trend_arrow(avg_trend)
        })

    krishna = next((row for row in aggregation if row["district"] == "KRISHNA"), None)
    ntr = next((row for row in aggregation if row["district"] == "NTR"), None)
    comparison_insight = None
    if krishna and ntr and krishna.get("avg_trend_slope") is not None and ntr.get("avg_trend_slope") is not None:
        if ntr["avg_trend_slope"] > krishna["avg_trend_slope"]:
            comparison_insight = "NTR shows faster groundwater depletion compared to Krishna."
        elif ntr["avg_trend_slope"] < krishna["avg_trend_slope"]:
            comparison_insight = "Krishna shows faster groundwater depletion compared to NTR."
        else:
            comparison_insight = "Krishna and NTR show similar groundwater trend slopes."

    return {
        "districts": aggregation,
        "comparison_insight": comparison_insight
    }


def _read_rows():
    rows = []
    if DATASET_PATH.exists():
        with DATASET_PATH.open("r", encoding="utf-8", newline="") as csv_file:
            rows.extend(list(csv.DictReader(csv_file)))

    if NTR_DATASET_PATH.exists():
        try:
            ntr_rows = json.loads(NTR_DATASET_PATH.read_text(encoding="utf-8"))
            if isinstance(ntr_rows, list):
                rows.extend([row for row in ntr_rows if isinstance(row, dict)])
        except json.JSONDecodeError:
            pass

    if not rows:
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")
    return rows


def _build_stats(rows, metrics):
    source_coverage = _load_source_coverage()
    if EXCLUDED_DISTRICTS:
        scoped_rows = [
            row for row in rows
            if str((row.get("district") or "")).strip().upper() not in EXCLUDED_DISTRICTS
        ]
    else:
        scoped_rows = list(rows)

    trend_values = []
    high_risk_count = 0
    anomaly_count = 0
    has_anomaly_field = False

    for row in scoped_rows:
        trend = _to_float(row.get("trend_slope"))
        if trend is not None:
            trend_values.append(trend)

        risk_score = _to_float(row.get("risk_score"))
        if risk_score is not None and risk_score >= HIGH_RISK_THRESHOLD:
            high_risk_count += 1

        anomaly_value = row.get("anomaly_flag")
        if anomaly_value is not None:
            has_anomaly_field = True
            label = str(anomaly_value).strip().lower()
            if label and label not in {"normal", "none", "false", "0", "nan"}:
                anomaly_count += 1

    payload = {
        "villages": len(scoped_rows),
        "avg_trend_slope": round(_mean(trend_values), 4) if trend_values else None,
        "high_risk_count": high_risk_count,
        "anomaly_count": anomaly_count if has_anomaly_field else 0,
        "model": {
            "r2": _to_float(metrics.get("r2")),
            "rmse": _to_float(metrics.get("rmse")),
            "mae": _to_float(metrics.get("mae"))
        },
        "snapshot": _build_snapshot(scoped_rows),
        "source_excel": source_coverage,
        "district_aggregation": _build_district_aggregation(scoped_rows, source_coverage),
        "meta": {
            "risk_threshold": HIGH_RISK_THRESHOLD,
            "rows_total": len(rows),
            "rows_in_scope": len(scoped_rows),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_dataset": [
                *( [str(DATASET_PATH.relative_to(ROOT))] if DATASET_PATH.exists() else [] ),
                *( [str(NTR_DATASET_PATH.relative_to(ROOT))] if NTR_DATASET_PATH.exists() else [] )
            ],
            "source_metrics": str(METRICS_PATH.relative_to(ROOT))
        }
    }
    if EXCLUDED_DISTRICTS:
        payload["meta"]["excluded_districts"] = sorted(EXCLUDED_DISTRICTS)
    return payload


def main():
    rows = _read_rows()
    metrics = _load_metrics()
    payload = _build_stats(rows, metrics)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote homepage stats to {OUTPUT_PATH}")


if __name__ == "__main__":
  main()
