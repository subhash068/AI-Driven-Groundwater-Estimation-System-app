from __future__ import annotations

import json
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
        if numeric != numeric:
            return default
        return numeric
    except (TypeError, ValueError):
        return default


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


@lru_cache(maxsize=1)
def _map_geojson() -> dict:
    data = _load_json(DATA_DIR / "map_data_predictions.geojson", {})
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return data
    fallback = _load_json(DATA_DIR / "villages.geojson", {})
    if isinstance(fallback, dict) and fallback.get("type") == "FeatureCollection":
        return fallback
    return {"type": "FeatureCollection", "features": []}


@lru_cache(maxsize=1)
def _final_rows() -> list[dict]:
    data = _load_json(DATA_DIR / "final_dataset.json", [])
    if isinstance(data, list):
        return data
    return []


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
    for feature in _map_geojson().get("features", []):
        props = feature.get("properties", {}) or {}
        village_id = int(_to_float(props.get("village_id"), default=-1) or -1)
        if village_id > 0:
            lookup[village_id] = feature
    return lookup


@lru_cache(maxsize=1)
def _final_lookup() -> dict[int, dict]:
    lookup: dict[int, dict] = {}
    for row in _final_rows():
        village_id = int(_to_float(row.get("Village_ID"), default=-1) or -1)
        if village_id > 0:
            lookup[village_id] = row
    return lookup


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
            SELECT
                village_id,
                village_name,
                district,
                mandal,
                estimated_groundwater_depth AS predicted_groundwater_level,
                confidence_score,
                risk_level,
                anomaly_flag,
                draft_index,
                forecast_3_month,
                geometry
            FROM groundwater.village_dashboard
            ORDER BY village_id
            """
        )
        rows = (await db.execute(query)).mappings().all()
        if rows:
            features: list[dict] = []
            for row in rows:
                raw_geom = row.get("geometry")
                if isinstance(raw_geom, str):
                    try:
                        raw_geom = json.loads(raw_geom)
                    except json.JSONDecodeError:
                        raw_geom = None
                features.append(
                    {
                        "type": "Feature",
                        "geometry": raw_geom,
                        "properties": {
                            "village_id": row.get("village_id"),
                            "village_name": row.get("village_name"),
                            "district": row.get("district"),
                            "mandal": row.get("mandal"),
                            "predicted_groundwater_level": _to_float(row.get("predicted_groundwater_level")),
                            "confidence": _to_float(row.get("confidence_score")),
                            "risk_level": row.get("risk_level"),
                            "anomaly_flag": bool(row.get("anomaly_flag")),
                            "draft_index": _to_float(row.get("draft_index"), 0.0),
                            "forecast_3_month": row.get("forecast_3_month") or [],
                        },
                    }
                )
            return {"type": "FeatureCollection", "features": features}
    except Exception:
        pass
    return _map_geojson()


async def fetch_predict(db: AsyncSession, village_id: int) -> dict | None:
    try:
        query = text(
            """
            SELECT
                village_id,
                estimated_groundwater_depth AS predicted_groundwater_level,
                confidence_score,
                risk_level,
                draft_index,
                forecast_3_month
            FROM groundwater.village_dashboard
            WHERE village_id = :village_id
            LIMIT 1
            """
        )
        row = (await db.execute(query, {"village_id": village_id})).mappings().first()
        if row:
            return {
                "village_id": int(row["village_id"]),
                "predicted_groundwater_level": _to_float(row.get("predicted_groundwater_level")),
                "confidence_score": _to_float(row.get("confidence_score")),
                "risk_level": row.get("risk_level") or "Unknown",
                "draft_index": _to_float(row.get("draft_index"), 0.0),
                "forecast_3_month": row.get("forecast_3_month") or [],
            }
    except Exception:
        pass

    feature = _map_lookup().get(village_id)
    if not feature:
        return None
    props = feature.get("properties", {}) or {}
    predicted = _to_float(props.get("predicted_groundwater_level"))
    return {
        "village_id": village_id,
        "predicted_groundwater_level": predicted,
        "confidence_score": _to_float(props.get("confidence"), 0.0),
        "risk_level": props.get("risk_level") or "Unknown",
        "draft_index": _to_float(props.get("draft_index"), 0.0),
        "forecast_3_month": _build_forecast_series(None, predicted),
    }


async def fetch_village_status(db: AsyncSession, village_id: int) -> dict:
    try:
        query = text(
            """
            SELECT
                village_id,
                estimated_groundwater_depth AS current_depth,
                confidence_score,
                anomaly_flag,
                risk_level,
                forecast_3_month
            FROM groundwater.village_dashboard
            WHERE village_id = :village_id
            LIMIT 1
            """
        )
        row = (await db.execute(query, {"village_id": village_id})).mappings().first()
        if row:
            anomaly_flags: list[str] = []
            if bool(row.get("anomaly_flag")):
                anomaly_flags.append("Detected anomaly")
            if row.get("risk_level"):
                anomaly_flags.append(f"Risk level: {row.get('risk_level')}")
            return {
                "village_id": int(row["village_id"]),
                "current_depth": _to_float(row.get("current_depth")),
                "forecast_3_month": row.get("forecast_3_month") or [],
                "anomaly_flags": anomaly_flags,
                "confidence_score": _to_float(row.get("confidence_score")),
            }
    except Exception:
        pass

    final_row = _final_lookup().get(village_id, {})
    map_feature = _map_lookup().get(village_id, {})
    map_props = map_feature.get("properties", {}) if map_feature else {}

    current_depth = _to_float(final_row.get("actual_last_month"))
    if current_depth is None:
        current_depth = _to_float(final_row.get("GW_Level"))
    predicted_depth = _to_float(map_props.get("predicted_groundwater_level"))
    forecast = _build_forecast_series(current_depth, predicted_depth)

    anomaly_flags: list[str] = []
    long_term_avg = _to_float(final_row.get("long_term_avg"))
    if current_depth is not None and long_term_avg is not None:
        delta = current_depth - long_term_avg
        if delta > 2:
            anomaly_flags.append("Severe drop")
        elif delta > 1:
            anomaly_flags.append("Moderate drop")
        elif delta < -1:
            anomaly_flags.append("Rise")
        else:
            anomaly_flags.append("Normal")
    risk_level = str(map_props.get("risk_level") or "").strip()
    if risk_level:
        anomaly_flags.append(f"Risk level: {risk_level}")

    return {
        "village_id": village_id,
        "current_depth": current_depth,
        "forecast_3_month": forecast,
        "anomaly_flags": anomaly_flags,
        "confidence_score": _to_float(map_props.get("confidence"), 0.0),
    }


async def fetch_village_forecast_lstm(db: AsyncSession, village_id: int) -> dict:
    try:
        query = text(
            """
            SELECT
                village_id,
                model_name,
                forecast_date,
                predicted_groundwater_depth,
                predicted_lower,
                predicted_upper
            FROM groundwater.village_forecasts
            WHERE village_id = :village_id
            ORDER BY forecast_date ASC
            LIMIT 3
            """
        )
        rows = (await db.execute(query, {"village_id": village_id})).mappings().all()
        if rows:
            return {
                "village_id": village_id,
                "model_name": rows[0].get("model_name") or "lstm",
                "forecast_3_month": [
                    {
                        "forecast_date": str(row.get("forecast_date")),
                        "predicted_groundwater_depth": _to_float(row.get("predicted_groundwater_depth")),
                        "predicted_lower": _to_float(row.get("predicted_lower")),
                        "predicted_upper": _to_float(row.get("predicted_upper")),
                    }
                    for row in rows
                ],
            }
    except Exception:
        pass

    status = await fetch_village_status(db, village_id=village_id)
    return {
        "village_id": village_id,
        "model_name": "krishna-fallback-model",
        "forecast_3_month": status.get("forecast_3_month", []),
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
                COALESCE(ve.estimated_groundwater_depth, 0.0) AS groundwater_depth
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
                            "reason": "High permeability and groundwater stress zone",
                        },
                    }
                )
            return {"type": "FeatureCollection", "features": features}
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
                    "reason": "Recharge candidate from permeability and stress indicators",
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
                "anomaly_score": _to_float(props.get("deviation")),
                "detected_at": str(props.get("detected_at") or _iso_now()),
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
