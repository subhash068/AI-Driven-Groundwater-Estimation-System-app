from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.key import build_location_key
from .model_loader import get_feature_columns


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"


@dataclass
class FeatureBundle:
    village_id: int
    village_name: str
    district: str
    mandal: str
    latitude: float | None
    longitude: float | None
    as_of: date
    vector: list[float]
    feature_map: dict[str, float]
    context: dict[str, Any]


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric):
        return default
    return numeric


def _to_int(value: Any, default: int = 0) -> int:
    numeric = _to_float(value)
    if numeric is None:
        return default
    try:
        return int(numeric)
    except (TypeError, ValueError):
        return default


def _first_number(*values: Any, default: float = 0.0) -> float:
    for value in values:
        numeric = _to_float(value)
        if numeric is not None:
            return float(numeric)
    return float(default)


def _first_text(*values: Any, default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _safe_json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _record_key(record: dict[str, Any]) -> str:
    return build_location_key(
        record.get("district") or record.get("District"),
        record.get("mandal") or record.get("Mandal"),
        record.get("village_name") or record.get("Village_Name") or record.get("village"),
    )


def _feature_key(feature: dict[str, Any]) -> str:
    props = feature.get("properties", {}) if isinstance(feature, dict) else {}
    return build_location_key(
        props.get("district"),
        props.get("mandal"),
        props.get("village_name"),
    )


def _feature_completeness(record: dict[str, Any]) -> int:
    score = 0
    for value in (record or {}).values():
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                score += 1
            continue
        if isinstance(value, list):
            if value:
                score += 1
            continue
        if isinstance(value, (bool, int, float)):
            score += 1
    return score


@lru_cache(maxsize=1)
def _local_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for filename in ("final_dataset.json", "final_dataset_ntr.json"):
        payload = _safe_json_load(DATA_DIR / filename, [])
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, dict))
    return rows


@lru_cache(maxsize=1)
def _local_rows_lookup() -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[int, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for row in _local_rows():
        village_id = _to_int(row.get("village_id") or row.get("Village_ID"), default=-1)
        if village_id > 0:
            existing = by_id.get(village_id)
            if not existing or _feature_completeness(row) > _feature_completeness(existing):
                by_id[village_id] = row
        key = _record_key(row)
        if key:
            existing = by_key.get(key)
            if not existing or _feature_completeness(row) > _feature_completeness(existing):
                by_key[key] = row
    return by_id, by_key


@lru_cache(maxsize=1)
def _local_feature_lookup() -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[int, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    feature_files = (
        "map_data_predictions.geojson",
        "map_data_predictions_ntr.geojson",
        "villages.geojson",
        "village_boundaries.geojson",
        "villages_ntr.geojson",
        "village_boundaries_ntr.geojson",
    )
    for filename in feature_files:
        payload = _safe_json_load(DATA_DIR / filename, {})
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            continue
        for feature in payload.get("features", []):
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties", {}) or {}
            village_id = _to_int(props.get("village_id"), default=-1)
            if village_id > 0:
                existing = by_id.get(village_id)
                if not existing or _feature_completeness(props) > _feature_completeness(existing):
                    by_id[village_id] = props
            key = _feature_key(feature)
            if key:
                existing = by_key.get(key)
                if not existing or _feature_completeness(props) > _feature_completeness(existing):
                    by_key[key] = props
    return by_id, by_key


def _parse_numeric_series(value: Any) -> list[float]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
            raw = parsed if isinstance(parsed, list) else []
        except Exception:
            raw = []
    else:
        raw = []
    out: list[float] = []
    for item in raw:
        numeric = _to_float(item)
        if numeric is not None:
            out.append(float(numeric))
    return out


def _series_trend(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return 0.0, 0.0
    slope = (values[-1] - values[0]) / max(len(values) - 1, 1)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return float(slope), float(math.sqrt(max(variance, 0.0)))


def _aquifer_storage_factor(value: Any) -> float:
    text_value = str(value or "").strip().lower()
    if not text_value or text_value == "unknown":
        return 1.0
    if any(token in text_value for token in ("alluvium", "alluvial", "valley fill", "sandstone", "limestone", "shale", "unconsolidated")):
        return 1.35
    if any(token in text_value for token in ("laterite", "pediment", "weathered")):
        return 1.1
    if any(token in text_value for token in ("granite", "gneiss", "charnokite", "basalt", "quartzite", "schist", "khondalite")):
        return 0.7
    return 1.0


async def _query_village_context(db: AsyncSession, village_id: int) -> dict[str, Any] | None:
    query = text(
        """
        SELECT
            v.village_id,
            v.village_name,
            v.district,
            v.mandal,
            ST_Y(ST_PointOnSurface(v.geom)) AS latitude,
            ST_X(ST_PointOnSurface(v.geom)) AS longitude,
            vf.elevation_dem,
            vf.slope_deg,
            vf.proximity_rivers_tanks_km,
            vf.rainfall_variability,
            vf.rainfall_lag_1m,
            vf.lulc_code,
            hg.soil_type,
            hg.rock_formation,
            hg.permeability,
            hg.aquifer_depth_m,
            le.estimated_groundwater_depth,
            le.confidence_score,
            le.risk_level
        FROM groundwater.villages v
        LEFT JOIN groundwater.village_features vf ON vf.village_id = v.village_id
        LEFT JOIN groundwater.hydrogeology hg ON hg.village_id = v.village_id
        LEFT JOIN LATERAL (
            SELECT
                ve.estimated_groundwater_depth,
                ve.confidence_score,
                ve.risk_level
            FROM groundwater.village_estimates ve
            WHERE ve.village_id = v.village_id
            ORDER BY ve.model_run_at DESC
            LIMIT 1
        ) le ON TRUE
        WHERE v.village_id = :village_id
        LIMIT 1
        """
    )
    row = (await db.execute(query, {"village_id": village_id})).mappings().first()
    return dict(row) if row else None


async def _query_nearest_piezometers(db: AsyncSession, village_id: int, limit: int = 5) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT
            p.station_id,
            p.current_depth,
            ST_Distance(
                ST_Transform(ST_PointOnSurface(v.geom), 3857),
                ST_Transform(p.geom, 3857)
            ) / 1000.0 AS distance_km
        FROM groundwater.villages v
        JOIN groundwater.piezometers p ON TRUE
        WHERE v.village_id = :village_id
        ORDER BY v.geom <-> p.geom
        LIMIT :limit
        """
    )
    rows = (await db.execute(query, {"village_id": village_id, "limit": limit})).mappings().all()
    return [dict(row) for row in rows]


async def _query_recent_rainfall(db: AsyncSession, village_id: int, as_of: date) -> dict[str, float]:
    date_7 = as_of - timedelta(days=7)
    date_30 = as_of - timedelta(days=30)
    date_60 = as_of - timedelta(days=60)
    query = text(
        """
        SELECT
            COALESCE(SUM(r.rainfall_mm) FILTER (WHERE r.observed_date > :date_7), 0.0) AS rainfall_7d_sum,
            COALESCE(SUM(r.rainfall_mm) FILTER (WHERE r.observed_date > :date_30), 0.0) AS rainfall_30d_sum,
            COALESCE(AVG(r.rainfall_mm) FILTER (WHERE r.observed_date > :date_30), 0.0) AS rainfall_30d_avg
        FROM groundwater.villages v
        LEFT JOIN groundwater.rainfall_history r
            ON ST_Intersects(r.geom, v.geom)
           AND r.observed_date <= :as_of
           AND r.observed_date >= :date_60
        WHERE v.village_id = :village_id
        GROUP BY v.village_id
        """
    )
    row = (await db.execute(
        query,
        {
            "village_id": village_id,
            "as_of": as_of,
            "date_7": date_7,
            "date_30": date_30,
            "date_60": date_60,
        },
    )).mappings().first()
    if not row:
        return {"rainfall_7d_sum": 0.0, "rainfall_30d_sum": 0.0, "rainfall_30d_avg": 0.0}
    return {
        "rainfall_7d_sum": _first_number(row.get("rainfall_7d_sum"), default=0.0),
        "rainfall_30d_sum": _first_number(row.get("rainfall_30d_sum"), default=0.0),
        "rainfall_30d_avg": _first_number(row.get("rainfall_30d_avg"), default=0.0),
    }


def _weighted_depth_and_distance(neighbors: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    if not neighbors:
        return None, None
    weighted_sum = 0.0
    weight_total = 0.0
    nearest: float | None = None
    for item in neighbors:
        depth = _to_float(item.get("current_depth"))
        distance_km = _to_float(item.get("distance_km"))
        if depth is None:
            continue
        if distance_km is None:
            distance_km = 1.0
        nearest = distance_km if nearest is None else min(nearest, distance_km)
        safe_distance = max(distance_km, 0.05)
        weight = 1.0 / safe_distance
        weighted_sum += depth * weight
        weight_total += weight
    if weight_total <= 0:
        return None, nearest
    return weighted_sum / weight_total, nearest


def _build_soil_vector(
    feature_cols: list[str],
    soil_value: str,
) -> dict[str, float]:
    soil_feature_name = f"soil_{soil_value}"
    has_exact_soil = soil_feature_name in feature_cols
    vector: dict[str, float] = {}
    for col in feature_cols:
        if not col.startswith("soil_"):
            continue
        if col == soil_feature_name:
            vector[col] = 1.0
        elif col == "soil_Unknown" and not has_exact_soil:
            vector[col] = 1.0
        else:
            vector[col] = 0.0
    return vector


async def build_features(
    db: AsyncSession,
    village_id: int,
    as_of: date | None = None,
    nearest_neighbors: int = 5,
) -> FeatureBundle | None:
    as_of_date = as_of or date.today()
    feature_cols = get_feature_columns()
    try:
        db_row = await _query_village_context(db, village_id)
    except Exception:
        db_row = None

    by_id_rows, by_key_rows = _local_rows_lookup()
    by_id_features, by_key_features = _local_feature_lookup()

    local_row = by_id_rows.get(village_id)
    local_feature = by_id_features.get(village_id)

    district = _first_text(
        db_row.get("district") if db_row else None,
        local_row.get("district") if local_row else None,
        local_row.get("District") if local_row else None,
        local_feature.get("district") if local_feature else None,
        default="Unknown",
    )
    mandal = _first_text(
        db_row.get("mandal") if db_row else None,
        local_row.get("mandal") if local_row else None,
        local_row.get("Mandal") if local_row else None,
        local_feature.get("mandal") if local_feature else None,
        default="Unknown",
    )
    village_name = _first_text(
        db_row.get("village_name") if db_row else None,
        local_row.get("village_name") if local_row else None,
        local_row.get("Village_Name") if local_row else None,
        local_feature.get("village_name") if local_feature else None,
        default=f"Village {village_id}",
    )
    location_key = build_location_key(district, mandal, village_name)

    if local_row is None and location_key:
        local_row = by_key_rows.get(location_key)
    if local_feature is None and location_key:
        local_feature = by_key_features.get(location_key)

    if db_row is None and local_row is None and local_feature is None:
        return None

    try:
        neighbor_rows = await _query_nearest_piezometers(db, village_id=village_id, limit=max(1, nearest_neighbors))
    except Exception:
        neighbor_rows = []
    weighted_depth, nearest_distance_km = _weighted_depth_and_distance(neighbor_rows)

    try:
        rainfall = await _query_recent_rainfall(db, village_id=village_id, as_of=as_of_date)
    except Exception:
        rainfall = {"rainfall_7d_sum": 0.0, "rainfall_30d_sum": 0.0, "rainfall_30d_avg": 0.0}

    monthly_series = _parse_numeric_series(
        (local_row or {}).get("monthly_depths_full")
        or (local_row or {}).get("monthly_depths")
        or (local_feature or {}).get("monthly_depths_full")
        or (local_feature or {}).get("monthly_depths")
    )
    trend_fallback, seasonal_fallback = _series_trend(monthly_series)

    water_pct = _first_number(
        (local_row or {}).get("Water%"),
        (local_row or {}).get("water_pct"),
        (local_feature or {}).get("water_pct"),
        default=0.0,
    )
    trees_pct = _first_number(
        (local_row or {}).get("Trees%"),
        (local_row or {}).get("trees_pct"),
        (local_feature or {}).get("trees_pct"),
        default=0.0,
    )
    crops_pct = _first_number(
        (local_row or {}).get("Crops%"),
        (local_row or {}).get("crops_pct"),
        (local_feature or {}).get("crops_pct"),
        default=0.0,
    )
    built_pct = _first_number(
        (local_row or {}).get("Built%"),
        (local_row or {}).get("built_area_pct"),
        (local_feature or {}).get("built_area_pct"),
        default=0.0,
    )
    bare_pct = _first_number(
        (local_row or {}).get("Bare%"),
        (local_row or {}).get("bare_ground_pct"),
        (local_feature or {}).get("bare_ground_pct"),
        default=0.0,
    )
    rangeland_pct = _first_number(
        (local_row or {}).get("Rangeland%"),
        (local_row or {}).get("rangeland_pct"),
        (local_feature or {}).get("rangeland_pct"),
        default=0.0,
    )
    pumping_rate = _first_number(
        (local_row or {}).get("Pumping"),
        (local_row or {}).get("pumping_rate"),
        (local_feature or {}).get("pumping_rate"),
        (local_row or {}).get("pumping_estimated_draft_ha_m"),
        default=0.0,
    )
    pumping_functioning_wells = _first_number(
        (local_row or {}).get("pumping_functioning_wells"),
        (local_feature or {}).get("pumping_functioning_wells"),
        default=0.0,
    )
    pumping_monsoon_draft = _first_number(
        (local_row or {}).get("pumping_monsoon_draft_ha_m"),
        (local_feature or {}).get("pumping_monsoon_draft_ha_m"),
        (local_row or {}).get("pumping_estimated_draft_ha_m"),
        default=0.0,
    )
    elevation = _first_number(
        (local_row or {}).get("Elevation"),
        (local_row or {}).get("elevation"),
        (db_row or {}).get("elevation_dem"),
        default=0.0,
    )
    tank_count = _first_number((local_row or {}).get("tank_count"), default=0.0)
    wells_total = _first_number((local_row or {}).get("wells_total"), default=0.0)
    flooded_vegetation_pct = _first_number(
        (local_row or {}).get("flooded_vegetation_pct"),
        (local_feature or {}).get("flooded_vegetation_pct"),
        default=0.0,
    )
    obs_station_count = _first_number(
        (local_row or {}).get("obs_station_count"),
        (local_feature or {}).get("obs_station_count"),
        float(len(neighbor_rows)),
        default=0.0,
    )
    long_term_avg = _first_number(
        (local_row or {}).get("long_term_avg"),
        weighted_depth,
        (db_row or {}).get("estimated_groundwater_depth"),
        (local_row or {}).get("actual_last_month"),
        default=0.0,
    )
    trend_slope = _first_number((local_row or {}).get("trend_slope"), trend_fallback, default=0.0)
    seasonal_variation = _first_number((local_row or {}).get("seasonal_variation"), seasonal_fallback, default=0.0)
    rainfall_proxy = _to_float((local_row or {}).get("rainfall_proxy"))
    if rainfall_proxy is None:
        rainfall_proxy = min(100.0, max(0.0, rainfall.get("rainfall_30d_sum", 0.0) / 3.0))

    elevation_min = _to_float((local_row or {}).get("elevation_min"))
    elevation_max = _to_float((local_row or {}).get("elevation_max"))
    slope_deg = _to_float((db_row or {}).get("slope_deg"), default=0.0) or 0.0
    if elevation_min is None and elevation_max is None:
        terrain_from_map = _to_float((local_feature or {}).get("terrain_gradient"))
        if terrain_from_map is None:
            terrain_from_map = abs(slope_deg) * 100.0
        half_span = terrain_from_map / 2.0
        elevation_min = elevation - half_span
        elevation_max = elevation + half_span
    elif elevation_min is None:
        elevation_min = elevation_max - abs(slope_deg) * 100.0
    elif elevation_max is None:
        elevation_max = elevation_min + abs(slope_deg) * 100.0
    terrain_gradient = _first_number(
        (local_row or {}).get("terrain_gradient"),
        (local_feature or {}).get("terrain_gradient"),
        (elevation_max - elevation_min),
        default=0.0,
    )

    aquifer_type = _first_text(
        (local_row or {}).get("aquifer_type"),
        (local_row or {}).get("Aquifer_Type"),
        (db_row or {}).get("rock_formation"),
        (local_row or {}).get("aquifer_class"),
        default="Unknown",
    )
    aquifer_storage_factor = _first_number(
        (local_row or {}).get("aquifer_storage_factor"),
        (local_feature or {}).get("aquifer_storage_factor"),
        _aquifer_storage_factor(aquifer_type),
        default=1.0,
    )
    soil_value = _first_text(
        (local_row or {}).get("Soil"),
        (local_row or {}).get("soil"),
        (db_row or {}).get("soil_type"),
        default="Unknown",
    )

    recharge_index = water_pct + tank_count + rainfall_proxy
    pumping_norm = pumping_rate / (wells_total + 1.0)
    draft_per_well = pumping_monsoon_draft / (pumping_functioning_wells + 1.0)
    extraction_stress = pumping_norm
    recharge_factor = min(
        3.0,
        max(
            0.1,
            0.3
            + water_pct * 0.01
            + trees_pct * 0.008
            + rangeland_pct * 0.005
            + bare_pct * 0.002
            - built_pct * 0.006,
        ),
    )
    infiltration_score = water_pct * 0.9 + trees_pct * 0.8 + crops_pct * 0.6 - built_pct * 0.9
    groundwater_stress = pumping_rate / recharge_factor if recharge_factor else 0.0

    base_feature_map = {
        "Water%": float(water_pct),
        "Trees%": float(trees_pct),
        "Crops%": float(crops_pct),
        "Built%": float(built_pct),
        "Bare%": float(bare_pct),
        "Rangeland%": float(rangeland_pct),
        "Pumping": float(pumping_rate),
        "pumping_functioning_wells": float(pumping_functioning_wells),
        "pumping_monsoon_draft_ha_m": float(pumping_monsoon_draft),
        "Elevation": float(elevation),
        "infiltration_score": float(infiltration_score),
        "recharge_factor": float(recharge_factor),
        "groundwater_stress": float(groundwater_stress),
        "pumping_norm": float(pumping_norm),
        "draft_per_well": float(draft_per_well),
        "recharge_index": float(recharge_index),
        "extraction_stress": float(extraction_stress),
        "terrain_gradient": float(terrain_gradient),
        "aquifer_storage_factor": float(aquifer_storage_factor),
        "obs_station_count": float(obs_station_count),
        "long_term_avg": float(long_term_avg),
        "trend_slope": float(trend_slope),
        "seasonal_variation": float(seasonal_variation),
    }
    soil_vector = _build_soil_vector(feature_cols, soil_value=soil_value)

    full_feature_map: dict[str, float] = {}
    for col in feature_cols:
        if col.startswith("soil_"):
            full_feature_map[col] = float(soil_vector.get(col, 0.0))
        else:
            full_feature_map[col] = float(base_feature_map.get(col, 0.0))

    vector = [float(full_feature_map[col]) for col in feature_cols]
    return FeatureBundle(
        village_id=village_id,
        village_name=village_name,
        district=district,
        mandal=mandal,
        latitude=_to_float((db_row or {}).get("latitude")),
        longitude=_to_float((db_row or {}).get("longitude")),
        as_of=as_of_date,
        vector=vector,
        feature_map=full_feature_map,
        context={
            "weighted_depth": _to_float(weighted_depth),
            "nearest_distance_km": _to_float(nearest_distance_km),
            "neighbor_count": len(neighbor_rows),
            "rainfall_7d_sum": float(rainfall.get("rainfall_7d_sum", 0.0)),
            "rainfall_30d_sum": float(rainfall.get("rainfall_30d_sum", 0.0)),
            "rainfall_30d_avg": float(rainfall.get("rainfall_30d_avg", 0.0)),
            "soil_type": soil_value,
            "aquifer_type": aquifer_type,
            "source_location_key": location_key,
        },
    )

