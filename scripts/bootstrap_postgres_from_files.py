from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

from backend.app.auth import get_password_hash


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DATA_DIR = ROOT / "frontend" / "public" / "data"
CSV_PATH = ROOT / "output" / "final_dataset.csv"
MAP_GEOJSON_PATH = ROOT / "data" / "exports" / "map_data.geojson"
MIGRATION_SQL_PATH = ROOT / "database" / "phase5_bootstrap.sql"


CONFIDENCE_DEFAULTS = {
    "measured": 1.0,
    "interpolated": 0.7,
    "derived": 0.5,
}
SAFE_RISK_MAX = 0.40
WARNING_RISK_MAX = 0.70


@dataclass
class TableCounter:
    inserted: int = 0
    updated: int = 0


def _log(message: str) -> None:
    now = datetime.now(UTC).isoformat()
    print(f"[{now}] {message}")


def _normalize_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_jsonish_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _slug_code(value: str, width: int = 4) -> str:
    alnum = re.sub(r"[^A-Za-z0-9]", "", value.upper())
    if not alnum:
        return "UNK0"[:width]
    if len(alnum) >= width:
        return alnum[:width]
    return (alnum + ("0" * width))[:width]


def _get_data_version() -> str:
    explicit = _normalize_text(os.getenv("DATA_VERSION"))
    if explicit:
        return explicit

    short_sha = ""
    try:
        short_sha = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT)
            .decode("utf-8")
            .strip()
        )
    except Exception:
        short_sha = "nogit"

    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{short_sha}"


def _connect_sync_db():
    dsn = _normalize_text(os.getenv("DB_DSN_SYNC"))
    if not dsn:
        async_dsn = _normalize_text(
            os.getenv("DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/groundwater")
        )
        dsn = async_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return psycopg2.connect(dsn)


def _load_frontend_json_sources() -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    if not FRONTEND_DATA_DIR.exists():
        return payloads
    for path in sorted(FRONTEND_DATA_DIR.glob("*.json")):
        try:
            payloads[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _log(f"Skipping invalid JSON: {path}")
    return payloads


def _load_csv_rows() -> list[dict[str, Any]]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _load_map_geojson() -> dict[str, Any]:
    if not MAP_GEOJSON_PATH.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(MAP_GEOJSON_PATH.read_text(encoding="utf-8"))


def _lookup_id(record: dict[str, Any], fallback_idx: int) -> int:
    for key in ("village_id", "Village_ID", "villageId", "id"):
        if key in record:
            parsed = _to_int(record.get(key))
            if parsed is not None:
                return parsed
    return fallback_idx


def _build_record_maps(
    frontend_json: dict[str, Any],
    csv_rows: list[dict[str, Any]],
    map_geojson: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[int, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    json_villages: dict[int, dict[str, Any]] = {}
    csv_villages: dict[int, dict[str, Any]] = {}
    geo_villages: dict[int, dict[str, Any]] = {}

    final_dataset_json = frontend_json.get("final_dataset.json", [])
    if isinstance(final_dataset_json, list):
        for idx, row in enumerate(final_dataset_json, start=1):
            if not isinstance(row, dict):
                continue
            village_id = _lookup_id(row, idx)
            json_villages[village_id] = row

    for idx, row in enumerate(csv_rows, start=1):
        village_id = _lookup_id(row, idx)
        csv_villages[village_id] = row

    for idx, feature in enumerate(map_geojson.get("features", []), start=1):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        village_id = _lookup_id(props, idx)
        geo_villages[village_id] = {
            "properties": props,
            "geometry": feature.get("geometry"),
        }

    anomalies = frontend_json.get("anomalies_krishna.json", {}).get("features", [])
    stations = frontend_json.get("krishna_piezometers.json", {}).get("stations", [])
    return json_villages, csv_villages, geo_villages, anomalies, stations


def _pick(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _get_field(json_row: dict[str, Any], csv_row: dict[str, Any], geo_props: dict[str, Any], *names: str) -> Any:
    for name in names:
        selected = _pick(json_row.get(name), csv_row.get(name), geo_props.get(name))
        if selected is not None:
            return selected
    return None


def _month_factors(month_labels: list[str], values: list[Any]) -> dict[int, float]:
    monthly_values: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    for label, value in zip(month_labels, values, strict=False):
        numeric = _to_float(value)
        if numeric is None:
            continue
        try:
            month = int(str(label)[5:7])
        except (TypeError, ValueError):
            continue
        if month < 1 or month > 12:
            continue
        monthly_values[month].append(numeric)

    overall: list[float] = [v for arr in monthly_values.values() for v in arr]
    baseline = (sum(overall) / len(overall)) if overall else 1.0
    if baseline <= 0:
        baseline = 1.0

    factors: dict[int, float] = {}
    for month in range(1, 13):
        arr = monthly_values[month]
        if arr:
            factors[month] = max(0.2, min(2.5, (sum(arr) / len(arr)) / baseline))
        else:
            factors[month] = 1.0
    return factors


def _derive_risk_score(depth: float, trend_slope: float, pumping: float, wells_working_pct: float) -> float:
    depth_component = max(0.0, min(1.0, depth / 20.0))
    trend_component = max(0.0, min(1.0, trend_slope * 10.0))
    pumping_component = max(0.0, min(1.0, pumping / 2.0))
    resilience_component = max(0.0, min(1.0, wells_working_pct / 100.0))
    score = (0.45 * depth_component) + (0.25 * trend_component) + (0.2 * pumping_component) + (0.1 * (1.0 - resilience_component))
    return max(0.0, min(1.0, round(score, 4)))


def _risk_to_level(risk_score: float) -> str:
    if risk_score < SAFE_RISK_MAX:
        return "safe"
    if risk_score < WARNING_RISK_MAX:
        return "warning"
    return "critical"


def _derive_external_id(village_name: str, mandal: str, district: str, village_id: int | None) -> str:
    if mandal and village_id is not None:
        mandal_code = _slug_code(mandal, width=4)
        village_code = str(village_id).zfill(4)
        return f"AP_KRISHNA_{mandal_code}_{village_code}"
    fallback_input = f"{village_name}|{mandal}|{district}".encode("utf-8")
    return hashlib.sha1(fallback_input).hexdigest()


def _apply_migration(conn) -> None:
    if not MIGRATION_SQL_PATH.exists():
        _log("phase5_bootstrap.sql not found; continuing without file-based migration")
        return
    sql = MIGRATION_SQL_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _record_bootstrap_log(
    conn,
    run_id: str,
    table_name: str,
    counter: TableCounter,
    status: str,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO groundwater.bootstrap_logs
                (run_id, table_name, inserted_count, updated_count, status, error)
            VALUES
                (%s, %s, %s, %s, %s, %s);
            """,
            (run_id, table_name, counter.inserted, counter.updated, status, error),
        )
    conn.commit()


def _upsert_and_count(cur, query: str, params: tuple[Any, ...], counter: TableCounter) -> None:
    cur.execute(query, params)
    row = cur.fetchone()
    if row is None:
        return
    inserted = bool(row and row[0])
    if inserted:
        counter.inserted += 1
    else:
        counter.updated += 1


def _ensure_admin_user(conn) -> None:
    username = _normalize_text(os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin"), "admin")
    password = _normalize_text(os.getenv("BOOTSTRAP_ADMIN_PASSWORD"), "ChangeMe123!")
    password_hash = get_password_hash(password)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO groundwater.app_users (username, full_name, password_hash, role)
            VALUES (%s, %s, %s, 'admin')
            ON CONFLICT (username)
            DO UPDATE SET
                full_name = EXCLUDED.full_name,
                password_hash = EXCLUDED.password_hash,
                role = EXCLUDED.role,
                is_active = TRUE;
            """,
            (username, "Bootstrap Admin", password_hash),
        )
    conn.commit()


def bootstrap() -> None:
    run_id = str(uuid.uuid4())
    mode = _normalize_text(os.getenv("BOOTSTRAP_MODE", "full"), "full").lower()
    data_version = _get_data_version()

    if mode not in {"full", "update"}:
        raise ValueError("BOOTSTRAP_MODE must be either 'full' or 'update'")

    _log(f"Starting bootstrap run_id={run_id} mode={mode} data_version={data_version}")

    frontend_json = _load_frontend_json_sources()
    csv_rows = _load_csv_rows()
    map_geojson = _load_map_geojson()

    json_villages, csv_villages, geo_villages, anomaly_features, piezometer_stations = _build_record_maps(
        frontend_json,
        csv_rows,
        map_geojson,
    )

    village_ids = sorted(set(json_villages) | set(csv_villages) | set(geo_villages))
    _log(f"Village rows discovered: {len(village_ids)}")

    conn = _connect_sync_db()

    try:
        _apply_migration(conn)

        tables: dict[str, TableCounter] = {
            "villages": TableCounter(),
            "hydrogeology": TableCounter(),
            "village_features": TableCounter(),
            "village_estimates": TableCounter(),
            "village_forecasts": TableCounter(),
            "village_anomalies": TableCounter(),
            "village_advisories": TableCounter(),
            "piezometers": TableCounter(),
        }

        anomaly_by_village: dict[int, dict[str, Any]] = {}
        for feature in anomaly_features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            village_id = _to_int(props.get("village_id"))
            if village_id is None:
                continue
            anomaly_by_village[village_id] = props

        with conn.cursor() as cur:
            for village_id in village_ids:
                json_row = json_villages.get(village_id, {})
                csv_row = csv_villages.get(village_id, {})
                geo = geo_villages.get(village_id, {})
                geo_props = geo.get("properties") or {}
                geometry = geo.get("geometry")

                village_name = _normalize_text(
                    _get_field(json_row, csv_row, geo_props, "Village_Name", "village_name"),
                    f"Village {village_id}",
                )
                district = _normalize_text(
                    _get_field(json_row, csv_row, geo_props, "District", "district"),
                    "KRISHNA",
                ).upper()
                mandal = _normalize_text(
                    _get_field(json_row, csv_row, geo_props, "Mandal", "mandal"),
                    "UNKNOWN",
                )

                population = _to_int(_get_field(json_row, csv_row, geo_props, "population"))
                if population is None:
                    population = 0

                external_id = _derive_external_id(village_name, mandal, district, village_id)
                census_id = f"CENSUS_{external_id}"

                if geometry is None:
                    continue

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.villages
                        (village_id, village_external_id, village_name, census_id, district, mandal, population, geom, source_type, source_file, confidence_score, data_version)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), %s, %s, %s, %s)
                    ON CONFLICT (village_id)
                    DO UPDATE SET
                        village_external_id = EXCLUDED.village_external_id,
                        village_name = EXCLUDED.village_name,
                        district = EXCLUDED.district,
                        mandal = EXCLUDED.mandal,
                        population = EXCLUDED.population,
                        geom = EXCLUDED.geom,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        confidence_score = EXCLUDED.confidence_score,
                        data_version = EXCLUDED.data_version,
                        updated_at = NOW()
                    RETURNING (xmax = 0);
                    """,
                    (
                        village_id,
                        external_id,
                        village_name,
                        census_id,
                        district,
                        mandal,
                        population,
                        json.dumps(geometry),
                        "measured",
                        "data/exports/map_data.geojson",
                        CONFIDENCE_DEFAULTS["measured"],
                        data_version,
                    ),
                    tables["villages"],
                )

                depth = _to_float(_get_field(json_row, csv_row, geo_props, "GW_Level", "depth", "actual_last_month", "target_last_month"))
                if depth is None:
                    depth = 0.0
                depth = max(0.0, depth)

                trend_slope = _to_float(_get_field(json_row, csv_row, geo_props, "trend_slope")) or 0.0
                pumping = _to_float(_get_field(json_row, csv_row, geo_props, "pumping_estimated_draft_ha_m", "Pumping", "pumping_functioning_wells")) or 0.0
                wells_working_pct = _to_float(_get_field(json_row, csv_row, geo_props, "wells_working_pct")) or 0.0

                risk_score = _derive_risk_score(depth, trend_slope, pumping, wells_working_pct)
                risk_level = _risk_to_level(risk_score)

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.village_estimates
                        (village_id, estimated_groundwater_depth, confidence_score, anomaly_flag, draft_index, source_type, source_file, data_version, risk_level)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (village_id, data_version)
                    DO UPDATE SET
                        estimated_groundwater_depth = EXCLUDED.estimated_groundwater_depth,
                        confidence_score = EXCLUDED.confidence_score,
                        anomaly_flag = EXCLUDED.anomaly_flag,
                        draft_index = EXCLUDED.draft_index,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        risk_level = EXCLUDED.risk_level,
                        model_run_at = NOW()
                    RETURNING (xmax = 0);
                    """,
                    (
                        village_id,
                        depth,
                        CONFIDENCE_DEFAULTS["interpolated"],
                        risk_level == "critical",
                        max(0.0, min(1.0, risk_score)),
                        "interpolated",
                        "output/final_dataset.csv",
                        data_version,
                        risk_level,
                    ),
                    tables["village_estimates"],
                )

                soil_type = _normalize_text(_get_field(json_row, csv_row, geo_props, "Soil", "soil", "aquifer_class"), "Unknown")
                rock_formation = _normalize_text(
                    _get_field(json_row, csv_row, geo_props, "fractured_rock", "weathered_rock", "aquifer_code"),
                    "Unknown",
                )
                permeability = _to_float(_get_field(json_row, csv_row, geo_props, "recharge_index", "water_pct"))
                if permeability is None:
                    permeability = 0.5
                permeability = max(0.0, min(1.0, permeability))

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.hydrogeology
                        (village_id, soil_type, rock_formation, permeability, source_type, source_file, confidence_score, data_version)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (village_id)
                    DO UPDATE SET
                        soil_type = EXCLUDED.soil_type,
                        rock_formation = EXCLUDED.rock_formation,
                        permeability = EXCLUDED.permeability,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        confidence_score = EXCLUDED.confidence_score,
                        data_version = EXCLUDED.data_version,
                        updated_at = NOW()
                    RETURNING (xmax = 0);
                    """,
                    (
                        village_id,
                        soil_type,
                        rock_formation,
                        permeability,
                        "derived",
                        "output/final_dataset.csv",
                        CONFIDENCE_DEFAULTS["derived"],
                        data_version,
                    ),
                    tables["hydrogeology"],
                )

                elevation = _to_float(_get_field(json_row, csv_row, geo_props, "Elevation", "obs_elevation_msl_mean"))
                slope = _to_float(_get_field(json_row, csv_row, geo_props, "terrain_gradient", "seasonal_variation"))
                distance_km = _to_float(
                    _get_field(
                        json_row,
                        csv_row,
                        geo_props,
                        "proximity_surface_water_km",
                        "distance_to_nearest_tank_km",
                    )
                )
                rain_var = _to_float(_get_field(json_row, csv_row, geo_props, "rainfall_proxy"))
                lulc_code = _to_int(_get_field(json_row, csv_row, geo_props, "lulc_latest_year"))

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.village_features
                        (village_id, elevation_dem, slope_deg, proximity_rivers_tanks_km, rainfall_variability, lulc_code, geomorphology_class, source_type, source_file, confidence_score, data_version)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (village_id)
                    DO UPDATE SET
                        elevation_dem = EXCLUDED.elevation_dem,
                        slope_deg = EXCLUDED.slope_deg,
                        proximity_rivers_tanks_km = EXCLUDED.proximity_rivers_tanks_km,
                        rainfall_variability = EXCLUDED.rainfall_variability,
                        lulc_code = EXCLUDED.lulc_code,
                        geomorphology_class = EXCLUDED.geomorphology_class,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        confidence_score = EXCLUDED.confidence_score,
                        data_version = EXCLUDED.data_version,
                        updated_at = NOW()
                    RETURNING (xmax = 0);
                    """,
                    (
                        village_id,
                        elevation,
                        slope,
                        distance_km,
                        rain_var,
                        lulc_code,
                        _normalize_text(_get_field(json_row, csv_row, geo_props, "geomorphology"), "Unknown"),
                        "derived",
                        "output/final_dataset.csv",
                        CONFIDENCE_DEFAULTS["derived"],
                        data_version,
                    ),
                    tables["village_features"],
                )

                depth_dates = _parse_jsonish_list(_get_field(json_row, csv_row, geo_props, "monthly_depths_dates", "monthly_depths_full_dates"))
                depth_values = _parse_jsonish_list(_get_field(json_row, csv_row, geo_props, "monthly_depths", "monthly_depths_full"))
                month_factors = _month_factors(depth_dates, depth_values)

                next_month = date.today().replace(day=1)
                base_value = depth
                for horizon in range(1, 4):
                    year = next_month.year + ((next_month.month - 1 + horizon) // 12)
                    month = ((next_month.month - 1 + horizon) % 12) + 1
                    forecast_date = date(year, month, 1)
                    raw_value = base_value + (trend_slope * horizon)
                    adjusted_value = max(0.0, raw_value * month_factors.get(month, 1.0))
                    lower = max(0.0, adjusted_value - (0.1 * adjusted_value))
                    upper = adjusted_value + (0.1 * adjusted_value)

                    _upsert_and_count(
                        cur,
                        """
                        INSERT INTO groundwater.village_forecasts
                            (village_id, forecast_date, predicted_groundwater_depth, predicted_lower, predicted_upper, model_name, source_type, source_file, confidence_score, data_version)
                        VALUES
                            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (village_id, forecast_date, model_name)
                        DO UPDATE SET
                            predicted_groundwater_depth = EXCLUDED.predicted_groundwater_depth,
                            predicted_lower = EXCLUDED.predicted_lower,
                            predicted_upper = EXCLUDED.predicted_upper,
                            source_type = EXCLUDED.source_type,
                            source_file = EXCLUDED.source_file,
                            confidence_score = EXCLUDED.confidence_score,
                            data_version = EXCLUDED.data_version
                        RETURNING (xmax = 0);
                        """,
                        (
                            village_id,
                            forecast_date,
                            round(adjusted_value, 3),
                            round(lower, 3),
                            round(upper, 3),
                            "deterministic_linear_seasonal",
                            "derived",
                            "output/final_dataset.csv",
                            CONFIDENCE_DEFAULTS["derived"],
                            data_version,
                        ),
                        tables["village_forecasts"],
                    )

                anomaly_props = anomaly_by_village.get(village_id)
                if anomaly_props:
                    anomaly_type = _normalize_text(anomaly_props.get("anomaly_type"), "source_anomaly")
                    anomaly_score = _to_float(anomaly_props.get("anomaly_score"))
                    detected_at = _normalize_text(anomaly_props.get("detected_at"), datetime.now(UTC).isoformat())
                    source_type = "measured"
                    source_file = "frontend/public/data/anomalies_krishna.json"
                    confidence = CONFIDENCE_DEFAULTS["measured"]
                elif risk_score >= WARNING_RISK_MAX:
                    anomaly_type = "risk_threshold_breach"
                    anomaly_score = risk_score
                    detected_at = datetime.now(UTC).isoformat()
                    source_type = "derived"
                    source_file = "output/final_dataset.csv"
                    confidence = CONFIDENCE_DEFAULTS["derived"]
                else:
                    anomaly_type = "normal_range"
                    anomaly_score = risk_score
                    detected_at = datetime.now(UTC).isoformat()
                    source_type = "derived"
                    source_file = "output/final_dataset.csv"
                    confidence = CONFIDENCE_DEFAULTS["derived"]

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.village_anomalies
                        (village_id, anomaly_type, anomaly_score, detected_at, source_type, source_file, confidence_score, data_version)
                    VALUES
                        (%s, %s, %s, %s::timestamptz, %s, %s, %s, %s)
                    ON CONFLICT (village_id, data_version, anomaly_type)
                    DO UPDATE SET
                        anomaly_score = EXCLUDED.anomaly_score,
                        detected_at = EXCLUDED.detected_at,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        confidence_score = EXCLUDED.confidence_score
                    RETURNING (xmax = 0);
                    """,
                    (
                        village_id,
                        anomaly_type,
                        anomaly_score,
                        detected_at,
                        source_type,
                        source_file,
                        confidence,
                        data_version,
                    ),
                    tables["village_anomalies"],
                )

                advisory_level = _risk_to_level(risk_score)
                advisory_texts = {
                    "safe": "Groundwater outlook is stable. Continue planned irrigation and monthly monitoring.",
                    "warning": "Groundwater stress is rising. Shift to water-efficient irrigation and stagger pumping.",
                    "critical": "Groundwater is critically stressed. Limit extraction and prioritize recharge interventions.",
                }

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.village_advisories
                        (village_id, advisory_level, advisory_text, language_code, channel, source_type, source_file, confidence_score, data_version)
                    VALUES
                        (%s, %s, %s, 'en', 'sms', %s, %s, %s, %s)
                    ON CONFLICT (village_id, data_version, advisory_level)
                    DO UPDATE SET
                        advisory_text = EXCLUDED.advisory_text,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        confidence_score = EXCLUDED.confidence_score
                    RETURNING (xmax = 0);
                    """,
                    (
                        village_id,
                        advisory_level,
                        advisory_texts[advisory_level],
                        "derived",
                        "output/final_dataset.csv",
                        CONFIDENCE_DEFAULTS["derived"],
                        data_version,
                    ),
                    tables["village_advisories"],
                )

            for station in piezometer_stations:
                station_id = _normalize_text(station.get("id"))
                if not station_id:
                    continue
                lat = _to_float(station.get("latitude"))
                lon = _to_float(station.get("longitude"))
                depth = _to_float(station.get("latestReading2024"))
                if lat is None or lon is None or depth is None:
                    continue
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                depth = max(0.0, depth)

                _upsert_and_count(
                    cur,
                    """
                    INSERT INTO groundwater.piezometers
                        (station_id, current_depth, status, geom, source_type, source_file, confidence_score, data_version)
                    VALUES
                        (%s, %s, 'active', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s)
                    ON CONFLICT (station_id)
                    DO UPDATE SET
                        current_depth = EXCLUDED.current_depth,
                        geom = EXCLUDED.geom,
                        source_type = EXCLUDED.source_type,
                        source_file = EXCLUDED.source_file,
                        confidence_score = EXCLUDED.confidence_score,
                        data_version = EXCLUDED.data_version,
                        observed_at = NOW()
                    RETURNING (xmax = 0);
                    """,
                    (
                        station_id,
                        depth,
                        lon,
                        lat,
                        "measured",
                        "frontend/public/data/krishna_piezometers.json",
                        CONFIDENCE_DEFAULTS["measured"],
                        data_version,
                    ),
                    tables["piezometers"],
                )

        conn.commit()

        for table_name, counter in tables.items():
            _record_bootstrap_log(conn, run_id, table_name, counter, status="success")
            _log(f"{table_name}: inserted={counter.inserted} updated={counter.updated}")

        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW groundwater.village_dashboard;")
        conn.commit()
        _log("Refreshed materialized view groundwater.village_dashboard")

        _ensure_admin_user(conn)
        _log("Ensured bootstrap admin user")

        _log("Bootstrap completed successfully")
    except Exception as exc:
        conn.rollback()
        _record_bootstrap_log(conn, run_id, "bootstrap", TableCounter(), status="failed", error=str(exc))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    bootstrap()
