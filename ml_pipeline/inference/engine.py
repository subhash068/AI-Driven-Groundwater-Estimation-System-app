from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from .feature_builder import FeatureBundle, build_features
from .model_loader import get_model


def _risk_level_from_depth(depth: float) -> str:
    score = depth * 5.0
    if score > 60:
        return "high"
    if score > 30:
        return "medium"
    return "low"


def _forecast_3m_from_prediction(
    predicted_depth: float,
    trend_slope: float,
    rainfall_30d_sum: float,
) -> list[dict[str, float | str]]:
    now = date.today().replace(day=1)
    # Higher rainfall tends to reduce groundwater depth (water table becomes shallower).
    rainfall_adjustment = min(0.4, max(-0.4, rainfall_30d_sum / 1200.0))
    output: list[dict[str, float | str]] = []
    for step in range(1, 4):
        year = now.year + ((now.month - 1 + step) // 12)
        month = ((now.month - 1 + step) % 12) + 1
        stamp = date(year, month, 1).isoformat()
        depth = max(0.0, predicted_depth + trend_slope * step - rainfall_adjustment * step)
        output.append(
            {
                "forecast_date": stamp,
                "predicted_groundwater_depth": round(depth, 3),
                "predicted_lower": round(max(0.0, depth - 0.4), 3),
                "predicted_upper": round(depth + 0.4, 3),
                "model_name": "xgb_live_inference",
            }
        )
    return output


def _forecast_yearly_from_prediction(
    predicted_depth: float,
    trend_slope: float,
    rainfall_30d_sum: float,
    years: int = 2,
) -> list[dict[str, float | str]]:
    now = date.today().replace(month=1, day=1)
    yearly_trend = trend_slope * 12.0
    rainfall_adjustment = min(1.5, max(-1.5, rainfall_30d_sum / 300.0))
    output: list[dict[str, float | str]] = []
    for step in range(1, years + 1):
        year = now.year + step
        stamp = date(year, 1, 1).isoformat()
        depth = max(0.0, predicted_depth + yearly_trend * step - rainfall_adjustment * step)
        output.append(
            {
                "forecast_date": stamp,
                "predicted_groundwater_depth": round(depth, 3),
                "predicted_lower": round(max(0.0, depth - 0.8), 3),
                "predicted_upper": round(depth + 0.8, 3),
                "model_name": "xgb_live_inference",
            }
        )
    return output


def _anomaly_from_prediction(predicted_depth: float, bundle: FeatureBundle) -> tuple[bool, float, str]:
    reference = bundle.context.get("weighted_depth")
    if reference is None:
        reference = bundle.feature_map.get("long_term_avg")
    if reference is None:
        return False, 0.0, "insufficient_reference"
    denominator = max(abs(float(reference)), 1.0)
    score = min(1.0, abs(predicted_depth - float(reference)) / denominator)
    if score < 0.15:
        return False, round(score, 4), "normal"
    if predicted_depth > float(reference):
        return True, round(score, 4), "rapid_drop"
    return True, round(score, 4), "rapid_recovery"


def _confidence(bundle: FeatureBundle) -> float:
    obs_count = float(bundle.context.get("neighbor_count") or 0.0)
    nearest_distance = float(bundle.context.get("nearest_distance_km") or 20.0)
    count_component = min(1.0, obs_count / 5.0)
    distance_component = max(0.0, 1.0 - (nearest_distance / 25.0))
    score = 0.35 + 0.4 * count_component + 0.25 * distance_component
    return round(max(0.0, min(1.0, score)), 4)


async def predict_groundwater_live(
    db: AsyncSession,
    village_id: int,
    as_of: date | None = None,
    nearest_neighbors: int = 5,
) -> dict[str, Any] | None:
    bundle = await build_features(
        db=db,
        village_id=village_id,
        as_of=as_of,
        nearest_neighbors=nearest_neighbors,
    )
    if bundle is None:
        return None

    model = get_model()
    prediction = float(model.predict(np.asarray([bundle.vector], dtype=float))[0])
    prediction = round(max(0.0, prediction), 6)
    risk_level = _risk_level_from_depth(prediction)
    forecast_3_month = _forecast_3m_from_prediction(
        predicted_depth=prediction,
        trend_slope=float(bundle.feature_map.get("trend_slope", 0.0)),
        rainfall_30d_sum=float(bundle.context.get("rainfall_30d_sum", 0.0)),
    )
    forecast_yearly = _forecast_yearly_from_prediction(
        predicted_depth=prediction,
        trend_slope=float(bundle.feature_map.get("trend_slope", 0.0)),
        rainfall_30d_sum=float(bundle.context.get("rainfall_30d_sum", 0.0)),
    )
    anomaly_flag, anomaly_score, anomaly_type = _anomaly_from_prediction(prediction, bundle)
    confidence_score = _confidence(bundle)
    return {
        "village_id": bundle.village_id,
        "village_name": bundle.village_name,
        "district": bundle.district,
        "mandal": bundle.mandal,
        "predicted_groundwater_level": prediction,
        "confidence_score": confidence_score,
        "risk_level": risk_level,
        "draft_index": round(float(bundle.feature_map.get("extraction_stress", 0.0)), 4),
        "forecast_3_month": forecast_3_month,
        "forecast_yearly": forecast_yearly,
        "anomaly_flag": anomaly_flag,
        "anomaly_score": anomaly_score,
        "anomaly_type": anomaly_type,
        "model_name": "xgb_live_inference",
        "mode": "live",
        "feature_snapshot": {
            "obs_station_count": round(float(bundle.feature_map.get("obs_station_count", 0.0)), 3),
            "long_term_avg": round(float(bundle.feature_map.get("long_term_avg", 0.0)), 3),
            "trend_slope": round(float(bundle.feature_map.get("trend_slope", 0.0)), 6),
            "seasonal_variation": round(float(bundle.feature_map.get("seasonal_variation", 0.0)), 6),
            "nearest_piezometer_distance_km": bundle.context.get("nearest_distance_km"),
            "rainfall_7d_sum": bundle.context.get("rainfall_7d_sum"),
            "rainfall_30d_sum": bundle.context.get("rainfall_30d_sum"),
        },
    }
