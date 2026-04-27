from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_INGEST_DIR = PROJECT_ROOT / "data" / "raw" / "airflow_ingestion"
PIPELINE_NAME = "groundwater_ingestion"
DEFAULT_START_DATE = datetime(2024, 1, 1, tzinfo=timezone.utc)


SOURCE_CONFIGS: dict[str, dict[str, Any]] = {
    "rainfall": {
        "env_names": ["IMD_RAINFALL_API", "TRMM_RAINFALL_API"],
        "raw_subdir": "rainfall",
    },
    "piezometer": {
        "env_names": ["PIEZOMETER_API"],
        "raw_subdir": "piezometer",
    },
    "lulc": {
        "env_names": ["SENTINEL_LULC_API"],
        "raw_subdir": "lulc",
    },
}


def _sync_dsn() -> str:
    dsn = os.getenv("DB_DSN_SYNC", "").strip()
    if dsn:
        return dsn
    async_dsn = os.getenv(
        "DB_DSN",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/groundwater",
    ).strip()
    return async_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _engine():
    return create_engine(_sync_dsn(), pool_pre_ping=True, future=True)


def _pick_source_endpoint(env_names: list[str]) -> tuple[str, str]:
    for env_name in env_names:
        endpoint = os.getenv(env_name, "").strip()
        if endpoint:
            return env_name, endpoint
    raise AirflowFailException(
        "No source endpoint configured. Set one of: " + ", ".join(env_names)
    )


def _fetch_payload(endpoint: str) -> Any:
    response = requests.get(endpoint, timeout=120)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        text_payload = response.text.strip()
        return text_payload if text_payload else {}


def _count_records(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("features", "stations", "items", "records", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return 1 if payload else 0
    return 1 if payload else 0


def _store_raw_payload(source_name: str, run_id: int, env_name: str, endpoint: str, payload: Any) -> Path:
    target_dir = RAW_INGEST_DIR / source_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"run_{run_id}.json"
    envelope = {
        "pipeline_name": PIPELINE_NAME,
        "source_name": source_name,
        "source_env": env_name,
        "endpoint": endpoint,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    target_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return target_path


def _create_run(conn, source_name: str) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO groundwater.ingestion_runs
                (pipeline_name, source_name, status)
            VALUES
                (:pipeline_name, :source_name, 'running')
            RETURNING run_id;
            """
        ),
        {"pipeline_name": PIPELINE_NAME, "source_name": source_name},
    )
    return int(result.scalar_one())


def _finish_run(
    conn,
    run_id: int,
    status: str,
    records_ingested: int = 0,
    error_message: str | None = None,
) -> None:
    conn.execute(
        text(
            """
            UPDATE groundwater.ingestion_runs
            SET
                finished_at = NOW(),
                status = :status,
                records_ingested = :records_ingested,
                error_message = :error_message
            WHERE run_id = :run_id;
            """
        ),
        {
            "run_id": run_id,
            "status": status,
            "records_ingested": records_ingested,
            "error_message": error_message,
        },
    )


def _run_source_ingestion(source_name: str) -> dict[str, Any]:
    config = SOURCE_CONFIGS[source_name]
    env_name, endpoint = _pick_source_endpoint(config["env_names"])
    engine = _engine()
    run_id: int | None = None
    status = "failed"
    records_ingested = 0
    error_message: str | None = None
    output_path: Path | None = None

    try:
        with engine.begin() as conn:
            run_id = _create_run(conn, source_name)

        payload = _fetch_payload(endpoint)
        records_ingested = _count_records(payload)
        if run_id is None:
            raise AirflowFailException("Failed to create ingestion run record.")
        output_path = _store_raw_payload(source_name, run_id, env_name, endpoint, payload)
        status = "success"
        return {
            "run_id": run_id,
            "source_name": source_name,
            "endpoint": endpoint,
            "source_env": env_name,
            "records_ingested": records_ingested,
            "status": status,
            "raw_path": str(output_path),
        }
    except Exception as exc:
        error_message = str(exc)
        if run_id is None:
            raise AirflowFailException(f"{source_name} ingestion could not start: {exc}") from exc
        raise AirflowFailException(f"{source_name} ingestion failed: {exc}") from exc
    finally:
        if run_id is not None:
            with engine.begin() as conn:
                _finish_run(
                    conn,
                    run_id=run_id,
                    status=status,
                    records_ingested=records_ingested,
                    error_message=error_message,
                )
        engine.dispose()


@dag(
    dag_id="groundwater_ingestion",
    description="Fetch rainfall, piezometer, and LULC payloads into raw storage and track run status.",
    schedule="@daily",
    start_date=DEFAULT_START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "groundwater",
        "depends_on_past": False,
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["groundwater", "ingestion", "postgis"],
)
def groundwater_ingestion_dag():
    @task
    def ingest_rainfall() -> dict[str, Any]:
        return _run_source_ingestion("rainfall")

    @task
    def ingest_piezometer() -> dict[str, Any]:
        return _run_source_ingestion("piezometer")

    @task
    def ingest_lulc() -> dict[str, Any]:
        return _run_source_ingestion("lulc")

    @task(trigger_rule="all_done")
    def summarize_runs(results: list[dict[str, Any]]) -> dict[str, Any]:
        successes = [item for item in results if item.get("status") == "success"]
        return {
            "pipeline_name": PIPELINE_NAME,
            "task_count": len(results),
            "successful_tasks": len(successes),
            "records_ingested": sum(int(item.get("records_ingested", 0)) for item in successes),
        }

    summarize_runs([ingest_rainfall(), ingest_piezometer(), ingest_lulc()])


dag = groundwater_ingestion_dag()
