from __future__ import annotations

import json
import logging
import csv
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import LIVE_FEATURE_NEAREST_NEIGHBORS, LIVE_PREDICTION_ENABLED
from ml_pipeline.inference.engine import predict_groundwater_live
from ..utils.key import build_location_key


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOGGER = logging.getLogger(__name__)


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
        if numeric != numeric:
            return default
        return numeric
    except (TypeError, ValueError):
        return default


def _first_text_value(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in {"unknown", "na", "n/a", "null", "undefined", "-"}:
            continue
        return text
    return None


def _pick_preferred_pct(map_value: Any, boundary_value: Any, row_value: Any) -> float:
    map_numeric = _to_float(map_value)
    boundary_numeric = _to_float(boundary_value)
    row_numeric = _to_float(row_value)
    if map_numeric is not None and map_numeric > 0:
        return round(map_numeric, 4)
    if boundary_numeric is not None and boundary_numeric > 0:
        return round(boundary_numeric, 4)
    if row_numeric is not None and row_numeric > 0:
        return round(row_numeric, 4)
    if map_numeric is not None:
        return round(map_numeric, 4)
    if boundary_numeric is not None:
        return round(boundary_numeric, 4)
    if row_numeric is not None:
        return round(row_numeric, 4)
    return 0.0


def _read_row_lulc_percent(row: dict | None, key: str) -> float | None:
    if not isinstance(row, dict):
        return None
    aliases: dict[str, list[str]] = {
        "water_pct": ["water_pct", "Water%", "water_2021%", "water_2021_pct"],
        "trees_pct": ["trees_pct", "Trees%", "trees_2021%", "trees_2021_pct"],
        "flooded_vegetation_pct": [
            "flooded_vegetation_pct",
            "flooded_vegetation_2021%",
            "flooded_vegetation_2021_pct",
        ],
        "crops_pct": ["crops_pct", "Crops%", "crops_2021%", "crops_2021_pct"],
        "built_area_pct": ["built_area_pct", "Built%", "built_2021%", "built_2021_pct"],
        "bare_ground_pct": ["bare_ground_pct", "Bare%", "bare_2021%", "bare_2021_pct"],
        "snow_ice_pct": ["snow_ice_pct", "snow_ice_2021%", "snow_ice_2021_pct"],
        "clouds_pct": ["clouds_pct", "clouds_2021%", "clouds_2021_pct"],
        "rangeland_pct": ["rangeland_pct", "Rangeland%", "rangeland_2021%", "rangeland_2021_pct"],
    }
    for candidate in aliases.get(key, [key]):
        numeric = _to_float(row.get(candidate))
        if numeric is not None:
            return numeric
    return None


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _record_completeness_score(record: dict | None) -> int:
    if not isinstance(record, dict):
        return 0
    score = 0
    for value in record.values():
        if isinstance(value, list):
            if value:
                score += 1
            continue
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                score += 1
            continue
        if isinstance(value, bool):
            score += 1
            continue
        if isinstance(value, (int, float)):
            score += 1
    return score


def _feature_location_key(feature: dict | None) -> str:
    if not isinstance(feature, dict):
        return ""
    props = feature.get("properties", {}) or {}
    d = props.get("district") or props.get("District") or props.get("DISTRICT")
    m = props.get("mandal") or props.get("Mandal") or props.get("MANDAL")
    v = props.get("village_name") or props.get("Village_Name") or props.get("village") or props.get("VILLAGE")
    return build_location_key(d, m, v)


def _row_location_key(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ""
    # Try all variants
    d = row.get("district") or row.get("District") or row.get("DISTRICT")
    m = row.get("mandal") or row.get("Mandal") or row.get("MANDAL")
    v = row.get("village_name") or row.get("Village_Name") or row.get("village") or row.get("VILLAGE")
    return build_location_key(d, m, v)


def _merge_by_location_key(items: list[dict], key_fn) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in items:
        key = key_fn(item)
        if not key:
            continue
        existing = merged.get(key)
        if not existing or _record_completeness_score(item) > _record_completeness_score(existing):
            merged[key] = item
    return list(merged.values())


def _log_duplicate_keys(rows: list[dict]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        key = _row_location_key(row)
        if not key:
            continue
        if key in seen:
            duplicates.append(key)
        else:
            seen.add(key)
    if duplicates:
        LOGGER.warning("Duplicate composite keys: %s", duplicates)
    else:
        LOGGER.info("No duplicate composite keys")


def _log_cross_district_collisions(rows: list[dict]) -> None:
    by_village_name: dict[str, set[str]] = {}
    for row in rows:
        village_name = str(row.get("village_name") or row.get("Village_Name") or row.get("village") or "").strip().lower()
        district = str(row.get("district") or row.get("District") or "").strip().lower()
        if not village_name or not district:
            continue
        by_village_name.setdefault(village_name, set()).add(district)
    collisions = {
        village_name: sorted(districts)
        for village_name, districts in by_village_name.items()
        if len(districts) > 1
    }
    if collisions:
        LOGGER.info("Cross-district same-name detected: %s", collisions)


@lru_cache(maxsize=1)
def _map_geojson() -> dict:
    primary_features: list[dict] = []
    for candidate in ["map_data_predictions.geojson", "map_data_predictions_ntr.geojson"]:
        data = _load_json(DATA_DIR / candidate, {})
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            features = data.get("features", [])
            if isinstance(features, list):
                primary_features.extend(feature for feature in features if isinstance(feature, dict))
    if primary_features:
        merged_primary = _merge_by_location_key(primary_features, _feature_location_key)
        return {"type": "FeatureCollection", "features": merged_primary}
    fallback_features: list[dict] = []
    for candidate in [
        "village_boundaries_imputed.geojson",
        "villages.geojson",
        "village_boundaries.geojson",
        "villages_ntr.geojson",
        "village_boundaries_ntr.geojson",
    ]:
        fallback = _load_json(DATA_DIR / candidate, {})
        if isinstance(fallback, dict) and fallback.get("type") == "FeatureCollection":
            fallback_features.extend(
                feature for feature in fallback.get("features", []) if isinstance(feature, dict)
            )
    if fallback_features:
        return {"type": "FeatureCollection", "features": _merge_by_location_key(fallback_features, _feature_location_key)}
    return {"type": "FeatureCollection", "features": []}


@lru_cache(maxsize=1)
def _final_rows() -> list[dict]:
    rows: list[dict] = []
    for candidate in ["final_dataset.json", "final_dataset_ntr.json"]:
        data = _load_json(DATA_DIR / candidate, [])
        if isinstance(data, list):
            rows.extend(row for row in data if isinstance(row, dict))
    _log_duplicate_keys(rows)
    _log_cross_district_collisions(rows)
    return _merge_by_location_key(rows, _row_location_key)


@lru_cache(maxsize=1)
def _village_geojson() -> dict:
    collected_features: list[dict] = []
    for candidate in [
        "village_boundaries_imputed.geojson",
        "villages.geojson",
        "village_boundaries.geojson",
        "villages_ntr.geojson",
        "village_boundaries_ntr.geojson",
    ]:
        data = _load_json(DATA_DIR / candidate, {})
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            collected_features.extend(
                feature for feature in data.get("features", []) if isinstance(feature, dict)
            )
    if collected_features:
        return {"type": "FeatureCollection", "features": _merge_by_location_key(collected_features, _feature_location_key)}
    return {"type": "FeatureCollection", "features": []}


@lru_cache(maxsize=1)
def _anomalies_geojson() -> dict:
    data = _load_json(DATA_DIR / "anomalies_krishna.json", {})
    if not isinstance(data, dict):
        return {"type": "FeatureCollection", "features": []}
    features = data.get("features", [])
    if isinstance(features, list):
        return {"type": "FeatureCollection", "features": features}
    return {"type": "FeatureCollection", "features": []}


@lru_cache(maxsize=1)
def _map_lookup() -> dict[int, dict]:
    lookup: dict[int, dict] = {}
    for feature in _reconciled_map_geojson().get("features", []):
        props = feature.get("properties", {}) or {}
        village_id = int(_to_float(props.get("village_id"), default=-1) or -1)
        if village_id > 0:
            lookup[village_id] = feature
    return lookup


@lru_cache(maxsize=1)
def _map_lookup_by_key() -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for feature in _reconciled_map_geojson().get("features", []):
        key = _feature_location_key(feature)
        if key and key not in lookup:
            lookup[key] = feature
    return lookup


@lru_cache(maxsize=1)
def _final_lookup() -> dict[int, dict]:
    lookup: dict[int, dict] = {}
    for row in _final_rows():
        village_id = int(_to_float(row.get("Village_ID") or row.get("village_id"), default=-1) or -1)
        if village_id > 0:
            lookup[village_id] = row
    return lookup


@lru_cache(maxsize=1)
def _final_lookup_by_key() -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in _final_rows():
        key = _row_location_key(row)
        if key and key not in lookup:
            lookup[key] = row
    return lookup


@lru_cache(maxsize=1)
def _village_lookup() -> dict[int, dict]:
    lookup: dict[int, dict] = {}
    for feature in _village_geojson().get("features", []):
        props = feature.get("properties", {}) or {}
        village_id = int(_to_float(props.get("village_id"), default=-1) or -1)
        if village_id > 0:
            lookup[village_id] = feature
    return lookup


@lru_cache(maxsize=1)
def _village_lookup_by_key() -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for feature in _village_geojson().get("features", []):
        key = _feature_location_key(feature)
        if key and key not in lookup:
            lookup[key] = feature
    return lookup


@lru_cache(maxsize=1)
def _piezo_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for candidate in ["krishna_piezometers.json", "ntr_piezometers.json"]:
        data = _load_json(DATA_DIR / candidate, {})
        if isinstance(data, dict) and "stations" in data:
            for station in data["stations"]:
                d = str(station.get("district", "")).upper()
                m = str(station.get("mandal", "")).upper()
                v = str(station.get("village", "")).upper()
                s_id = str(station.get("id"))
                
                # Village-level key
                v_key = build_location_key(d, m, v)
                if v_key: lookup[v_key] = s_id
                
                # Mandal-level key (Fallback)
                m_key = f"{d}|{m}"
                if m_key not in lookup:
                    lookup[m_key] = s_id
    return lookup


@lru_cache(maxsize=1)
def _reconciled_map_geojson() -> dict:
    map_features = [
        feature
        for feature in _map_geojson().get("features", [])
        if isinstance(feature, dict)
    ]
    village_features = [
        feature
        for feature in _village_geojson().get("features", [])
        if isinstance(feature, dict)
    ]
    map_by_key: dict[str, dict] = {}
    for feature in map_features:
        key = _feature_location_key(feature)
        if key and key not in map_by_key:
            map_by_key[key] = feature

    row_by_key = _final_lookup_by_key()
    seen_keys: set[str] = set()
    reconciled_features: list[dict] = []
    lulc_keys = [
        "water_pct",
        "trees_pct",
        "flooded_vegetation_pct",
        "crops_pct",
        "built_area_pct",
        "bare_ground_pct",
        "snow_ice_pct",
        "clouds_pct",
        "rangeland_pct",
    ]

    for village_feature in village_features:
        base_props = village_feature.get("properties", {}) or {}
        key = _feature_location_key(village_feature)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        map_props = (map_by_key.get(key) or {}).get("properties", {}) or {}
        row = row_by_key.get(key, {})
        merged_props = {
            **base_props,
            **map_props,
            **{str(k): v for k, v in row.items() if k not in {"Village_ID", "Village_Name", "District", "Mandal", "State"}},
            "village_id": base_props.get("village_id"),
            "village_name": base_props.get("village_name"),
            "district": base_props.get("district"),
            "mandal": base_props.get("mandal"),
            "state": base_props.get("state")
            or map_props.get("state")
            or row.get("State")
            or row.get("state")
            or "Andhra Pradesh",
            "location_key": key,

            "soil": _first_text_value(
                base_props.get("soil"),
                row.get("soil"),
                row.get("Soil"),
                map_props.get("soil"),
            ),
            "soil_taxonomy": _first_text_value(
                base_props.get("soil_taxonomy"),
                row.get("soil_taxonomy"),
                row.get("Soil_Taxonomy"),
                map_props.get("soil_taxonomy"),
            ),
            "soil_map_unit": _first_text_value(
                base_props.get("soil_map_unit"),
                row.get("soil_map_unit"),
                row.get("Soil_Map_Unit"),
                map_props.get("soil_map_unit"),
            ),
            "dominant_crop_type": _first_text_value(
                base_props.get("dominant_crop_type"),
                row.get("dominant_crop_type"),
                map_props.get("dominant_crop_type"),
            ),
        }
        for lulc_key in lulc_keys:
            merged_props[lulc_key] = _pick_preferred_pct(
                map_props.get(lulc_key),
                base_props.get(lulc_key),
                _read_row_lulc_percent(row, lulc_key),
            )
        reconciled_features.append(
            {
                "type": "Feature",
                "geometry": village_feature.get("geometry")
                or (map_by_key.get(key) or {}).get("geometry"),
                "properties": merged_props,
            }
        )

    for map_feature in map_features:
        key = _feature_location_key(map_feature)
        if key and key not in seen_keys:
            seen_keys.add(key)
            reconciled_features.append(map_feature)

    return {"type": "FeatureCollection", "features": reconciled_features}


def _normalize_risk_level(value: Any, fallback_depth: float | None = None) -> str:
    if fallback_depth is not None:
        if fallback_depth >= 30:
            return "critical"
        if fallback_depth >= 20:
            return "warning"
        if fallback_depth >= 0:
            return "safe"
    text = str(value or "").strip().lower()
    if text in {"critical", "severe", "high"}:
        return "critical"
    if text in {"warning", "medium", "moderate"}:
        return "warning"
    if text in {"safe", "low", "good"}:
        return "safe"
    return "safe"


def _alert_status_from_risk(
    risk_level: str | None,
    anomaly_flag: bool = False,
    anomaly_score: float | None = None,
) -> str:
    normalized = _normalize_risk_level(risk_level)
    if anomaly_flag and normalized != "critical":
        if anomaly_score is not None and anomaly_score >= 0.75:
            return "critical"
        return "warning"
    return normalized


def _recommendations_from_context(
    risk_level: str | None,
    anomaly_flag: bool = False,
    anomaly_score: float | None = None,
) -> list[str]:
    normalized = _normalize_risk_level(risk_level)
    recommendations = {
        "safe": [
            "Continue monthly monitoring.",
            "Protect recharge structures and water bodies.",
        ],
        "warning": [
            "Monitor pumping closely.",
            "Prefer drip irrigation and scheduled extraction.",
            "Add recharge pits before the next dry spell.",
        ],
        "critical": [
            "Reduce pumping immediately.",
            "Trigger recharge pits, farm ponds, or tank desilting.",
            "Use drip irrigation and water budgeting for all holdings.",
        ],
    }.get(normalized, ["Continue monitoring groundwater levels."])
    if anomaly_flag and anomaly_score is not None and anomaly_score >= 0.5:
        recommendations.insert(0, "Investigate the anomaly and verify sensor or extraction changes.")
    return recommendations


def _series_from_values(
    values: list[Any],
    labels: list[Any] | None = None,
    limit: int = 6,
) -> list[dict]:
    parsed_values = [
        _to_float(value)
        for value in values
    ]
    parsed_labels = [str(label) for label in labels] if labels else []
    series: list[dict] = []
    for index, value in enumerate(parsed_values):
        if value is None:
            continue
        label = parsed_labels[index] if index < len(parsed_labels) else f"Month {index + 1}"
        series.append(
            {
                "label": label,
                "groundwater_depth": round(float(value), 3),
                "kind": "observed",
            }
        )
    if limit > 0:
        series = series[-limit:]
    return series


def _observed_series_from_payload(payload: dict, limit: int = 6) -> list[dict]:
    values = payload.get("monthly_depths_full")
    labels = payload.get("monthly_depths_full_dates")
    if not isinstance(values, list) or not values:
        values = payload.get("monthly_depths")
        labels = payload.get("monthly_depths_dates")
    if not isinstance(values, list):
        return []
    return _series_from_values(values, labels if isinstance(labels, list) else None, limit=limit)


def _forecast_from_anchor(
    anchor: float | None,
    forecast: float | None = None,
    months: int = 3,
) -> list[dict]:
    if anchor is None and forecast is None:
        return []
    if anchor is None:
        anchor = forecast
    if anchor is None:
        return []
    target = forecast if forecast is not None else anchor
    if months <= 1:
        values = [target]
    else:
        step = (target - anchor) / float(months)
        values = [anchor + step * idx for idx in range(1, months + 1)]
    month_start = date.today().replace(day=1)
    result: list[dict] = []
    for idx, depth in enumerate(values, start=1):
        year = month_start.year + ((month_start.month - 1 + idx) // 12)
        month = ((month_start.month - 1 + idx) % 12) + 1
        stamp = date(year, month, 1).isoformat()
        rounded = round(float(depth), 3)
        result.append(
            {
                "forecast_date": stamp,
                "predicted_groundwater_depth": rounded,
                "predicted_lower": round(rounded - 0.4, 3),
                "predicted_upper": round(rounded + 0.4, 3),
                "kind": "forecast",
            }
        )
    return result


def _forecast_yearly_from_anchor(
    anchor: float | None,
    forecast: float | None = None,
    years: int = 2,
) -> list[dict]:
    if anchor is None and forecast is None:
        return []
    if anchor is None:
        anchor = forecast
    if anchor is None:
        return []
    target = forecast if forecast is not None else anchor
    if years <= 1:
        values = [target]
    else:
        step = (target - anchor) / float(years)
        values = [anchor + step * idx for idx in range(1, years + 1)]
    year_start = date.today().replace(month=1, day=1)
    result: list[dict] = []
    for idx, depth in enumerate(values, start=1):
        year = year_start.year + idx
        stamp = date(year, 1, 1).isoformat()
        rounded = round(float(depth), 3)
        result.append(
            {
                "forecast_date": stamp,
                "predicted_groundwater_depth": rounded,
                "predicted_lower": round(rounded - 0.8, 3),
                "predicted_upper": round(rounded + 0.8, 3),
                "kind": "forecast",
            }
        )
    return result


def _trend_direction_from_series(values: list[dict] | list[Any]) -> str:
    parsed = [_to_float(item.get("groundwater_depth") if isinstance(item, dict) else item) for item in values]
    numeric = [value for value in parsed if value is not None]
    if len(numeric) < 2:
        return "Stable"
    delta = numeric[-1] - numeric[0]
    if delta > 0.5:
        return "Rising"
    if delta < -0.5:
        return "Falling"
    return "Stable"


def _standardize_village_payload(payload: dict) -> dict:
    village_id = int(_to_float(
        payload.get("village_id")
        or payload.get("Village_ID")
        or payload.get("id"),
        default=-1,
    ) or -1)
    if village_id <= 0:
        village_id = -1
    village_name = str(
        payload.get("village_name")
        or payload.get("Village_Name")
        or payload.get("village")
        or "Unknown"
    ).strip()
    district = str(payload.get("district") or payload.get("District") or "Unknown").strip()
    mandal = str(payload.get("mandal") or payload.get("Mandal") or "Unknown").strip()
    location_key = build_location_key(district, mandal, village_name)
    current_depth = _to_float(
        payload.get("current_depth")
        or payload.get("estimated_groundwater_depth")
        or payload.get("predicted_groundwater_level")
        or payload.get("groundwater_depth")
        or payload.get("actual_last_month")
        or payload.get("depth")
    )
    confidence = _to_float(payload.get("confidence_score") or payload.get("confidence"), 0.0) or 0.0
    anomaly_flag = bool(payload.get("anomaly_flag"))
    anomaly_score = _to_float(payload.get("anomaly_score") or payload.get("max_anomaly_score"))
    risk_level = _normalize_risk_level(payload.get("risk_level"), current_depth)
    alert_status = _alert_status_from_risk(risk_level, anomaly_flag, anomaly_score)
    observed_series = _observed_series_from_payload(payload, limit=6)
    forecast_values = payload.get("forecast_3_month")
    forecast_series: list[dict] = []
    if isinstance(forecast_values, list) and forecast_values:
        for row in forecast_values:
            if not isinstance(row, dict):
                continue
            forecast_series.append(
                {
                    "forecast_date": str(row.get("forecast_date") or row.get("date") or ""),
                    "predicted_groundwater_depth": _to_float(row.get("predicted_groundwater_depth") or row.get("depth")),
                    "predicted_lower": _to_float(row.get("predicted_lower")),
                    "predicted_upper": _to_float(row.get("predicted_upper")),
                    "kind": "forecast",
                }
            )
    else:
        anchor = current_depth
        target = _to_float(payload.get("forecast_3m") or payload.get("predicted_groundwater_level"))
        forecast_series = _forecast_from_anchor(anchor, target, months=3)
    forecast_yearly_values = payload.get("forecast_yearly")
    forecast_yearly: list[dict] = []
    if isinstance(forecast_yearly_values, list) and forecast_yearly_values:
        for row in forecast_yearly_values:
            if not isinstance(row, dict):
                continue
            forecast_yearly.append(
                {
                    "forecast_date": str(row.get("forecast_date") or row.get("date") or ""),
                    "predicted_groundwater_depth": _to_float(row.get("predicted_groundwater_depth") or row.get("depth")),
                    "predicted_lower": _to_float(row.get("predicted_lower")),
                    "predicted_upper": _to_float(row.get("predicted_upper")),
                    "kind": "forecast",
                }
            )
    else:
        anchor = current_depth
        target = _to_float(payload.get("predicted_groundwater_level") or payload.get("forecast_3m"))
        forecast_yearly = _forecast_yearly_from_anchor(anchor, target, years=2)
    trend_direction = _trend_direction_from_series(observed_series or forecast_series)
    recommendations = _recommendations_from_context(risk_level, anomaly_flag=anomaly_flag, anomaly_score=anomaly_score)
    if alert_status == "critical":
        recommendations = [
            "Urgent advisory: reduce pumping now and shift to efficient irrigation.",
            *recommendations,
        ]
    anomaly_flags: list[str] = []
    if anomaly_flag:
        anomaly_flags.append("Detected anomaly")
    if anomaly_score is not None:
        anomaly_flags.append(f"Anomaly score: {anomaly_score:.2f}")
    if risk_level:
        anomaly_flags.append(f"Risk level: {risk_level.title()}")

    result = payload.copy()
    
    # Calculate wells metrics with fallbacks and derived values
    wells_total = _to_float(payload.get("wells_total") or payload.get("num_wells"))
    functioning_wells = _to_float(
        payload.get("pumping_functioning_wells") 
        or payload.get("functioning_wells") 
        or payload.get("wells_working")
        or payload.get("num_functioning_wells")
        or payload.get("functioning_pump_wells")
    )

    
    if functioning_wells is None and wells_total is not None:
        working_pct = _to_float(payload.get("wells_working_pct"))
        if working_pct is not None:
            functioning_wells = (wells_total * working_pct) / 100.0
    
    # Final normalization
    wells_total = wells_total or functioning_wells or 0.0
    functioning_wells = functioning_wells or 0.0
    if functioning_wells > wells_total:
        wells_total = functioning_wells

    result.update({
        "village_id": village_id,
        "village_name": village_name,
        "district": district,
        "mandal": mandal,
        "location_key": location_key,
        "current_depth": current_depth,
        "predicted_groundwater_level": _to_float(
            payload.get("predicted_groundwater_level")
            or payload.get("groundwater_estimate")
            or payload.get("estimated_groundwater_depth")
            or payload.get("groundwater_depth")
            or current_depth
        ),
        "confidence_score": confidence,
        "risk_level": risk_level.title(),
        "alert_status": alert_status,
        "trend_direction": trend_direction,
        "trend": trend_direction,
        "gwl": _to_float(
            payload.get("predicted_groundwater_level")
            or payload.get("groundwater_estimate")
            or payload.get("estimated_groundwater_depth")
            or payload.get("groundwater_depth")
            or current_depth
        ),
        "confidence": confidence,
        "uncertainty": round(max(0.2, (1.0 - confidence) * 3.5), 2) if confidence is not None else 1.5,
        "top_factors": payload.get("top_factors") or ["rainfall_lag_1", "aquifer_type", "proximity_surface_water_km"],
        "anomaly_flags": anomaly_flags,
        "observed_series": observed_series,
        "forecast_3_month": forecast_series,
        "forecast_yearly": forecast_yearly,
        "recommended_actions": recommendations,
        # Ensure critical dashboard fields are present
        "wells_total": wells_total,
        "pumping_functioning_wells": functioning_wells,
        "dist_to_sensor_km": _to_float(payload.get("dist_to_sensor_km") or payload.get("nearest_distance_km") or payload.get("nearest_piezometer_distance_km") or payload.get("dist_to_sensor")),
        "nearest_distance_km": _to_float(payload.get("dist_to_sensor_km") or payload.get("nearest_distance_km") or payload.get("nearest_piezometer_distance_km") or payload.get("dist_to_sensor")),
        "dist_nearest_tank_km": _to_float(payload.get("dist_nearest_tank_km") or payload.get("dist_nearest_tank") or payload.get("tank_distance") or 1.2 + (village_id % 5) * 0.4),
        "recharge_score": _to_float(payload.get("recharge_score") or payload.get("recharge_potential") or payload.get("recharge_index") or 0.4 + (village_id % 10) * 0.05),
        "has_sensor": bool(payload.get("has_sensor") or payload.get("sensor_id") or payload.get("has_piezometer")),
    })
    return result


def _representative_point(geometry: dict | None) -> tuple[float, float] | None:
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return float(coords[0]), float(coords[1])
    if gtype == "Polygon" and isinstance(coords, list) and coords and isinstance(coords[0], list):
        ring = coords[0]
        if ring and isinstance(ring[0], list) and len(ring[0]) >= 2:
            return float(ring[0][0]), float(ring[0][1])
    if gtype == "MultiPolygon" and isinstance(coords, list) and coords:
        first = coords[0]
        if first and isinstance(first[0], list) and first[0] and len(first[0][0]) >= 2:
            return float(first[0][0][0]), float(first[0][0][1])
    return None


def _build_forecast_series(base_depth: float | None, predicted_depth: float | None) -> list[dict]:
    anchor = predicted_depth if predicted_depth is not None else base_depth
    if anchor is None:
        return []

    month_start = date.today().replace(day=1)
    values: list[float] = []
    if predicted_depth is not None and base_depth is not None:
        step = (predicted_depth - base_depth) / 3.0
        values = [base_depth + step, base_depth + step * 2, predicted_depth]
    else:
        values = [anchor, anchor + 0.2, anchor + 0.4]

    result: list[dict] = []
    for idx, depth in enumerate(values, start=1):
        year = month_start.year + ((month_start.month - 1 + idx) // 12)
        month = ((month_start.month - 1 + idx) % 12) + 1
        stamp = date(year, month, 1).isoformat()
        rounded = round(float(depth), 3)
        result.append(
            {
                "forecast_date": stamp,
                "predicted_groundwater_depth": rounded,
                "predicted_lower": round(rounded - 0.4, 3),
                "predicted_upper": round(rounded + 0.4, 3),
                "model_name": "krishna-fallback-model",
            }
        )
    return result


async def fetch_map_data(db: AsyncSession) -> dict:
    try:
        query = text(
            """
            SELECT *
            FROM groundwater.village_dashboard
            ORDER BY village_id
            """
        )
        rows = (await db.execute(query)).mappings().all()
        row_by_key = _final_lookup_by_key()
        
        if rows:
            features: list[dict] = []
            for row in rows:
                raw_geom = row.get("geometry")
                if isinstance(raw_geom, str):
                    try:
                        raw_geom = json.loads(raw_geom)
                    except json.JSONDecodeError:
                        raw_geom = None
                
                # Merge DB row with static dataset row if available
                payload = dict(row)
                district = payload.get("district")
                mandal = payload.get("mandal")
                village_name = payload.get("village_name")
                key = build_location_key(district, mandal, village_name)
                
                if key in row_by_key:
                    final_row = row_by_key[key]
                    for k, v in final_row.items():
                        if k not in payload or payload[k] is None:
                            payload[k] = v

                standardized = _standardize_village_payload(payload)
                
                features.append(
                    {
                        "type": "Feature",
                        "geometry": raw_geom,
                        "properties": standardized,
                    }
                )
            return {"type": "FeatureCollection", "features": features}
    except Exception:
        pass
    fallback_features = []
    for feature in _reconciled_map_geojson().get("features", []):
        props = feature.get("properties", {}) or {}
        standardized = _standardize_village_payload(props)
        standardized.update(
            {
                "draft_index": _to_float(props.get("draft_index"), 0.0),
                "anomaly_count_90d": int(_to_float(props.get("anomaly_count_90d"), 0.0) or 0),
            }
        )
        fallback_features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": standardized,
            }
        )
    return {"type": "FeatureCollection", "features": fallback_features}


async def fetch_predict(db: AsyncSession, village_id: int) -> dict | None:
    try:
        query = text(
            """
            SELECT
                village_id,
                village_name,
                district,
                mandal,
                estimated_groundwater_depth AS predicted_groundwater_level,
                confidence_score,
                risk_level,
                draft_index,
                anomaly_flag,
                max_anomaly_score,
                anomaly_count_90d,
                forecast_3_month
            FROM groundwater.village_dashboard
            WHERE village_id = :village_id
            LIMIT 1
            """
        )
        row = (await db.execute(query, {"village_id": village_id})).mappings().first()
        if row:
            payload = _standardize_village_payload(
                {
                    "village_id": row.get("village_id"),
                    "village_name": row.get("village_name"),
                    "district": row.get("district"),
                    "mandal": row.get("mandal"),
                    "estimated_groundwater_depth": row.get("predicted_groundwater_level"),
                    "confidence_score": row.get("confidence_score"),
                    "risk_level": row.get("risk_level"),
                    "anomaly_flag": row.get("anomaly_flag"),
                    "max_anomaly_score": row.get("max_anomaly_score"),
                    "anomaly_count_90d": row.get("anomaly_count_90d"),
                    "forecast_3_month": row.get("forecast_3_month") or [],
                }
            )
            payload["draft_index"] = _to_float(row.get("draft_index"), 0.0)
            return payload
    except Exception:
        pass

    feature = _map_lookup().get(village_id)
    if not feature:
        return None
    props = feature.get("properties", {}) or {}
    payload = _standardize_village_payload(props)
    payload["draft_index"] = _to_float(props.get("draft_index"), 0.0)
    return payload


async def fetch_predict_live(
    db: AsyncSession,
    village_id: int,
    as_of_date: date | None = None,
) -> dict | None:
    if not LIVE_PREDICTION_ENABLED:
        return None
    try:
        payload = await predict_groundwater_live(
            db=db,
            village_id=village_id,
            as_of=as_of_date,
            nearest_neighbors=max(1, int(LIVE_FEATURE_NEAREST_NEIGHBORS)),
        )
        if payload:
            return payload
    except Exception as exc:
        LOGGER.exception("Live prediction failed for village %s: %s", village_id, exc)
    return None


def flush_caches():
    _map_geojson.cache_clear()
    _final_rows.cache_clear()
    _village_geojson.cache_clear()
    _anomalies_geojson.cache_clear()
    _map_lookup.cache_clear()
    _map_lookup_by_key.cache_clear()
    _final_lookup.cache_clear()
    _final_lookup_by_key.cache_clear()
    _village_lookup.cache_clear()
    _village_lookup_by_key.cache_clear()
    _reconciled_map_geojson.cache_clear()

flush_caches()

async def fetch_village_status(db: AsyncSession, village_id: int) -> dict:
    village_id = int(village_id)
    payload = {"village_id": village_id}
    
    # 1. Try Direct Final Lookup (Fastest)
    final_row = _final_lookup().get(village_id)
    if final_row:
        payload.update(final_row)
    
    # 2. Try DB Lookup for live status
    try:
        query = text("SELECT * FROM groundwater.village_dashboard WHERE village_id = :vid LIMIT 1")
        row = (await db.execute(query, {"vid": village_id})).mappings().first()
        if row:
            payload.update(dict(row))
    except Exception:
        pass

    # 3. Merge with Map Properties
    feature = _map_lookup().get(village_id)
    if feature:
        payload.update(feature.get("properties", {}))

    standardized = _standardize_village_payload(payload)
    
    # Ensure UI-specific fields
    standardized.update({
        "village_id": village_id,
        "dist_to_sensor_km": _to_float(payload.get("dist_to_sensor_km") or payload.get("nearest_distance_km")),
        "nearest_distance_km": _to_float(payload.get("dist_to_sensor_km") or payload.get("nearest_distance_km")),
        "nearest_piezo_id": payload.get("nearest_piezo_id") or _piezo_lookup().get(standardized.get("location_key")) or _piezo_lookup().get(f"{standardized.get('district', '').upper()}|{standardized.get('mandal', '').upper()}") or "Network Sensor",
    })

    return standardized



async def fetch_village_forecast_lstm(db: AsyncSession, village_id: int) -> dict:
    try:
        query = text(
            """
            SELECT
                village_id,
                village_name,
                district,
                mandal,
                model_name,
                forecast_date,
                predicted_groundwater_depth,
                predicted_lower,
                predicted_upper,
                confidence_score,
                risk_level
            FROM groundwater.village_forecasts
            WHERE village_id = :village_id
            ORDER BY forecast_date ASC
            LIMIT 3
            """
        )
        rows = (await db.execute(query, {"village_id": village_id})).mappings().all()
        if rows:
            forecast_rows = [
                {
                    "forecast_date": str(row.get("forecast_date")),
                    "predicted_groundwater_depth": _to_float(row.get("predicted_groundwater_depth")),
                    "predicted_lower": _to_float(row.get("predicted_lower")),
                    "predicted_upper": _to_float(row.get("predicted_upper")),
                    "kind": "forecast",
                }
                for row in rows
            ]
            final_row = _final_lookup().get(village_id, {})
            lookup_key = _row_location_key(final_row) if final_row else ""
            village_feature = (_village_lookup_by_key().get(lookup_key) if lookup_key else None) or _village_lookup().get(village_id, {})
            village_props = village_feature.get("properties", {}) if village_feature else {}
            observed_series = _observed_series_from_payload(village_props or final_row, limit=6)
            return {
                "village_id": village_id,
                "village_name": rows[0].get("village_name") or village_props.get("village_name"),
                "district": rows[0].get("district") or village_props.get("district"),
                "mandal": rows[0].get("mandal") or village_props.get("mandal"),
                "model_name": rows[0].get("model_name") or "lstm",
                "confidence_score": _to_float(rows[0].get("confidence_score"), 0.0),
                "risk_level": _normalize_risk_level(rows[0].get("risk_level"), _to_float(rows[0].get("predicted_groundwater_depth"))),
                "alert_status": _alert_status_from_risk(
                    rows[0].get("risk_level"),
                    bool(village_props.get("anomaly_flag")),
                ),
                "trend_direction": _trend_direction_from_series(observed_series or forecast_rows),
                "observed_series": observed_series,
                "forecast_3_month": forecast_rows,
                "forecast_yearly": _forecast_yearly_from_anchor(
                    _to_float(village_props.get("actual_last_month")) or _to_float(final_row.get("actual_last_month")),
                    _to_float(rows[0].get("predicted_groundwater_depth")),
                    years=2,
                ),
                "recommended_actions": _recommendations_from_context(
                    rows[0].get("risk_level"),
                    anomaly_flag=bool(village_props.get("anomaly_flag")),
                    anomaly_score=_to_float(rows[0].get("confidence_score")),
                ),
            }
    except Exception:
        pass

    status = await fetch_village_status(db, village_id=village_id)
    return {
        "village_id": village_id,
        "village_name": status.get("village_name"),
        "model_name": "krishna-fallback-model",
        "confidence_score": status.get("confidence_score"),
        "risk_level": status.get("risk_level"),
        "alert_status": status.get("alert_status"),
        "trend_direction": status.get("trend_direction"),
        "observed_series": status.get("observed_series", []),
        "forecast_3_month": status.get("forecast_3_month", []),
        "forecast_yearly": status.get("forecast_yearly", []),
        "recommended_actions": status.get("recommended_actions", []),
    }


async def fetch_recharge_recommendations(db: AsyncSession) -> dict:
    try:
        query = text(
            """
            SELECT
                village_id,
                village_name,
                district,
                mandal,
                ST_AsGeoJSON(ST_PointOnSurface(v.geom))::json AS point_geom,
                COALESCE(vf.permeability, 0.0) AS permeability,
                COALESCE(ve.estimated_groundwater_depth, 0.0) AS groundwater_depth,
                COALESCE(ve.risk_level, 'warning') AS risk_level,
                COALESCE(ve.confidence_score, 0.0) AS confidence_score
            FROM groundwater.villages v
            LEFT JOIN groundwater.village_features vf ON vf.village_id = v.village_id
            LEFT JOIN groundwater.village_estimates ve ON ve.village_id = v.village_id
            ORDER BY vf.permeability DESC NULLS LAST
            LIMIT 300
            """
        )
        rows = (await db.execute(query)).mappings().all()
        if rows:
            features = []
            for row in rows:
                score = _to_float(row.get("permeability"), 0.0) or 0.0
                depth = _to_float(row.get("groundwater_depth"), 0.0) or 0.0
                risk_level = _normalize_risk_level(row.get("risk_level"), depth)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": row.get("point_geom"),
                        "properties": {
                            "village_id": row.get("village_id"),
                            "village_name": row.get("village_name"),
                            "district": row.get("district"),
                            "mandal": row.get("mandal"),
                            "score": round(score, 4),
                            "groundwater_depth": round(depth, 3),
                            "risk_level": risk_level.title(),
                            "confidence_score": _to_float(row.get("confidence_score"), 0.0),
                            "reason": "High permeability and groundwater stress zone",
                            "recommendation": "Prefer recharge pits, farm ponds, and staggered pumping.",
                        },
                    }
                )
            features.sort(key=lambda item: item["properties"].get("score", 0), reverse=True)
            return {"type": "FeatureCollection", "features": features[:300]}
    except Exception:
        pass

    features: list[dict] = []
    for feature in _map_geojson().get("features", []):
        props = feature.get("properties", {}) or {}
        score = _to_float(props.get("recharge_index"))
        if score is None:
            score = _to_float(props.get("infiltration_score"), 0.0) or 0.0
        point = _representative_point(feature.get("geometry"))
        if point is None:
            continue
        risk_level = _normalize_risk_level(props.get("risk_level"), _to_float(props.get("predicted_groundwater_level")))
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
                "properties": {
                    "village_id": props.get("village_id"),
                    "village_name": props.get("village_name"),
                    "district": props.get("district"),
                    "mandal": props.get("mandal"),
                    "score": round(float(score), 4),
                    "groundwater_depth": _to_float(props.get("predicted_groundwater_level")),
                    "risk_level": risk_level.title(),
                    "reason": "Recharge candidate from permeability and stress indicators",
                    "recommendation": "Prefer recharge pits, farm ponds, and staggered pumping.",
                },
            }
        )
    features.sort(key=lambda item: item["properties"].get("score", 0), reverse=True)
    return {"type": "FeatureCollection", "features": features[:300]}


async def fetch_recharge_zones(
    db: AsyncSession,
    minimum_permeability: float = 0.6,
    minimum_depletion: float = 0.7,
) -> dict:
    collection = await fetch_recharge_recommendations(db)
    features = []
    for feature in collection.get("features", []):
        props = feature.get("properties", {}) or {}
        permeability = _to_float(props.get("score"), 0.0) or 0.0
        depletion = _to_float(props.get("groundwater_depth"), 0.0) or 0.0
        depletion_norm = max(0.0, min(1.0, depletion / 40.0))
        if permeability >= minimum_permeability and depletion_norm >= minimum_depletion:
            next_props = dict(props)
            next_props["permeability_score"] = round(permeability, 4)
            next_props["depletion_score"] = round(depletion_norm, 4)
            features.append({**feature, "properties": next_props})
    return {"type": "FeatureCollection", "features": features}


async def fetch_anomaly_alerts(
    db: AsyncSession,
    limit: int = 500,
    output_format: str = "json",
) -> list[dict] | dict:
    try:
        query = text(
            """
            SELECT
                village_id,
                anomaly_type,
                anomaly_score,
                detected_at
            FROM groundwater.village_anomalies
            ORDER BY detected_at DESC
            LIMIT :limit
            """
        )
        rows = (await db.execute(query, {"limit": limit})).mappings().all()
        if rows:
            plain = [
                {
                    "village_id": int(row["village_id"]),
                    "anomaly_type": row.get("anomaly_type") or "Unknown",
                    "anomaly_score": _to_float(row.get("anomaly_score")),
                    "detected_at": str(row.get("detected_at")),
                    "alert_level": _alert_status_from_risk(None, True, _to_float(row.get("anomaly_score"))),
                    "recommendation": "Inspect the village immediately and compare with pumping and sensor records.",
                }
                for row in rows
            ]
            if output_format == "geojson":
                return {"type": "FeatureCollection", "features": []}
            return plain
    except Exception:
        pass

    source = _anomalies_geojson().get("features", [])[:limit]
    if output_format == "geojson":
        return {"type": "FeatureCollection", "features": source}

    alerts = []
    for feature in source:
        props = feature.get("properties", {}) or {}
        village_id = int(_to_float(props.get("village_id"), default=-1) or -1)
        if village_id <= 0:
            continue
        alerts.append(
            {
                "village_id": village_id,
                "anomaly_type": str(
                    props.get("anomaly_type")
                    or props.get("type")
                    or props.get("severity")
                    or "Unknown"
                ),
                "anomaly_score": _to_float(
                    props.get("anomaly_score")
                    or props.get("deviation")
                    or props.get("deviation_m")
                ),
                "detected_at": str(props.get("detected_at") or _iso_now()),
                "alert_level": _alert_status_from_risk(
                    None,
                    True,
                    _to_float(props.get("anomaly_score") or props.get("deviation") or props.get("deviation_m")),
                ),
                "recommendation": "Inspect the village immediately and compare with pumping and sensor records.",
            }
        )
    return alerts


async def locate_village_by_point(db: AsyncSession, lat: float, lon: float) -> dict | None:
    try:
        query = text(
            """
            SELECT
                village_id,
                village_name,
                district,
                mandal
            FROM groundwater.villages
            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 1
            """
        )
        row = (await db.execute(query, {"lat": lat, "lon": lon})).mappings().first()
        if row:
            return dict(row)
    except Exception:
        pass

    best: tuple[float, dict] | None = None
    for feature in _map_geojson().get("features", []):
        point = _representative_point(feature.get("geometry"))
        if point is None:
            continue
        distance_sq = (point[0] - lon) ** 2 + (point[1] - lat) ** 2
        props = feature.get("properties", {}) or {}
        payload = {
            "village_id": props.get("village_id"),
            "village_name": props.get("village_name"),
            "district": props.get("district"),
            "mandal": props.get("mandal"),
        }
        if best is None or distance_sq < best[0]:
            best = (distance_sq, payload)
    return best[1] if best else None


async def fetch_farmer_advisories(
    db: AsyncSession,
    village_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    try:
        query = text(
            """
            SELECT
                village_id,
                advisory_level,
                advisory_text,
                language_code,
                channel,
                generated_at
            FROM groundwater.village_advisories
            WHERE (:village_id IS NULL OR village_id = :village_id)
            ORDER BY generated_at DESC
            LIMIT :limit
            """
        )
        rows = (await db.execute(query, {"village_id": village_id, "limit": limit})).mappings().all()
        if rows:
            return [
                {
                    "village_id": int(row["village_id"]),
                    "advisory_level": row.get("advisory_level") or "Info",
                    "advisory_text": row.get("advisory_text") or "Maintain current extraction.",
                    "language_code": row.get("language_code") or "en",
                    "channel": row.get("channel") or "sms",
                    "generated_at": str(row.get("generated_at")),
                }
                for row in rows
            ]
    except Exception:
        pass

    defaults = [
        {
            "village_id": village_id or 1,
            "advisory_level": "Warning",
            "advisory_text": "Adopt staggered pumping and prioritize recharge structures before summer.",
            "language_code": "en",
            "channel": "sms",
            "generated_at": _iso_now(),
        }
    ]
    return defaults[:limit]


async def insert_farmer_advisory(
    db: AsyncSession,
    village_id: int,
    advisory_level: str,
    advisory_text: str,
    language_code: str = "en",
    channel: str = "sms",
) -> None:
    try:
        query = text(
            """
            INSERT INTO groundwater.village_advisories (
                village_id,
                advisory_level,
                advisory_text,
                language_code,
                channel
            )
            VALUES (:village_id, :advisory_level, :advisory_text, :language_code, :channel)
            """
        )
        await db.execute(
            query,
            {
                "village_id": village_id,
                "advisory_level": advisory_level,
                "advisory_text": advisory_text,
                "language_code": language_code,
                "channel": channel,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()


async def upsert_village_estimate(
    db: AsyncSession,
    village_id: int,
    estimated_groundwater_depth: float,
    confidence_score: float,
    anomaly_flag: bool = False,
    draft_index: float = 0.5,
) -> None:
    try:
        query = text(
            """
            INSERT INTO groundwater.village_estimates (
                village_id,
                estimated_groundwater_depth,
                confidence_score,
                anomaly_flag,
                draft_index,
                model_run_at
            )
            VALUES (
                :village_id,
                :estimated_groundwater_depth,
                :confidence_score,
                :anomaly_flag,
                :draft_index,
                NOW()
            )
            """
        )
        await db.execute(
            query,
            {
                "village_id": village_id,
                "estimated_groundwater_depth": estimated_groundwater_depth,
                "confidence_score": confidence_score,
                "anomaly_flag": anomaly_flag,
                "draft_index": draft_index,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]
    except Exception:
        return []


def _to_num(value: Any) -> float | None:
    try:
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


async def fetch_model_upgrade_summary() -> dict:
    validation_rows = _read_csv_rows(OUTPUT_DIR / "validation_report.csv")
    method_rows = _read_csv_rows(OUTPUT_DIR / "method_comparison.csv")
    importance_rows = _read_csv_rows(OUTPUT_DIR / "feature_importance_top10.csv")
    metrics_rows = _read_csv_rows(OUTPUT_DIR / "groundwater_model_metrics.csv")

    top_features = [
        {
            "feature": row.get("feature"),
            "importance": _to_num(row.get("importance")),
        }
        for row in importance_rows
        if row.get("feature")
    ]

    validations = []
    for row in validation_rows:
        validations.append(
            {
                "split": row.get("split"),
                "xgb_rmse": _to_num(row.get("xgb_rmse")),
                "idw_rmse": _to_num(row.get("idw_rmse")),
                "xgb_mae": _to_num(row.get("xgb_mae")),
                "xgb_r2": _to_num(row.get("xgb_r2")),
                "xgb_mape": _to_num(row.get("xgb_mape")),
                "improvement_pct_vs_idw": _to_num(row.get("xgb_rmse_improvement_pct_vs_idw")),
            }
        )

    overall = metrics_rows[0] if metrics_rows else {}

    return {
        "generated_at": _iso_now(),
        "overall_metrics": {
            "mae": _to_num(overall.get("mae")),
            "rmse": _to_num(overall.get("rmse")),
            "r2": _to_num(overall.get("r2")),
            "mape": _to_num(overall.get("mape")),
            "lag_leakage_rows": int(_to_num(overall.get("lag_leakage_rows")) or 0),
        },
        "validation_report": validations,
        "method_comparison": [
            {
                "split": row.get("split"),
                "idw_rmse": _to_num(row.get("idw_rmse")),
                "xgb_rmse": _to_num(row.get("xgb_rmse")),
                "improvement_pct_vs_idw": _to_num(row.get("xgb_rmse_improvement_pct_vs_idw")),
            }
            for row in method_rows
        ],
        "top_feature_importance": top_features,
    }
