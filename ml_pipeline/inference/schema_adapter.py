from __future__ import annotations

from typing import Any

import pandas as pd
import geopandas as gpd


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
        if numeric != numeric:
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def derive_risk(record: dict[str, Any]) -> str:
    gwl = _first_not_none(
        _to_float(record.get("predicted_groundwater_level")),
        _to_float(record.get("predicted_groundwater")),
        _to_float(record.get("groundwater_level")),
    )
    if gwl is None:
        return "unknown"
    if gwl < 5:
        return "critical"
    if gwl < 10:
        return "warning"
    return "safe"


def estimate_uncertainty(record: dict[str, Any]) -> float:
    candidates = [
        _to_float(record.get("uncertainty")),
        _to_float(record.get("uncertainty_std_nearby")),
        _to_float(record.get("predicted_abs_error")),
    ]
    for value in candidates:
        if value is not None and value >= 0:
            return round(value, 6)
    confidence = _to_float(record.get("confidence")) or _to_float(record.get("confidence_score"))
    if confidence is not None:
        conf01 = confidence / 100.0 if confidence > 1 else confidence
        conf01 = max(0.0, min(1.0, conf01))
        return round(max(0.0, 1.0 - conf01), 6)
    return 0.5


def normalize_prediction_record(record: dict[str, Any]) -> dict[str, Any]:
    predicted_gwl = _first_not_none(
        _to_float(record.get("predicted_groundwater_level")),
        _to_float(record.get("predicted_groundwater")),
        _to_float(record.get("groundwater_level")),
    )
    base_gwl = _first_not_none(
        _to_float(record.get("base_groundwater_level")),
        _to_float(record.get("groundwater_level")),
        _to_float(record.get("actual_last_month")),
        predicted_gwl,
    )
    confidence = _first_not_none(
        _to_float(record.get("confidence")),
        _to_float(record.get("confidence_score")),
    )
    if confidence is not None:
        confidence = confidence / 100.0 if confidence > 1 else confidence
        confidence = max(0.0, min(1.0, confidence))
    risk_level = str(record.get("risk_level") or derive_risk(record)).strip().lower()
    trend = str(record.get("trend") or record.get("trend_direction") or "stable").strip().lower()
    top_factors = record.get("top_factors")
    if not isinstance(top_factors, list):
        top_factors = []

    return {
        **record,
        "predicted_groundwater_level": round(float(predicted_gwl), 6) if predicted_gwl is not None else None,
        "base_groundwater_level": round(float(base_gwl), 6) if base_gwl is not None else None,
        "confidence": round(float(confidence), 6) if confidence is not None else None,
        "uncertainty": float(estimate_uncertainty(record)),
        "risk_level": risk_level or "unknown",
        "trend": trend or "stable",
        "top_factors": [str(item) for item in top_factors if str(item).strip()],
    }


def normalize_prediction_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    records = frame.to_dict(orient="records")
    normalized = [normalize_prediction_record(record) for record in records]
    if isinstance(frame, gpd.GeoDataFrame):
        geometry_col = frame.geometry.name if frame.geometry is not None else "geometry"
        return gpd.GeoDataFrame(normalized, geometry=geometry_col, crs=frame.crs)
    return pd.DataFrame(normalized)
