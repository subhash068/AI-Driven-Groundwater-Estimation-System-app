import os
from pathlib import Path


DB_DSN = os.getenv(
    "DB_DSN",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/groundwater",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change_me_in_production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_ARTIFACT_PATH = os.getenv(
    "MODEL_ARTIFACT_PATH",
    str(PROJECT_ROOT / "model" / "artifacts" / "model_xgb.json"),
)
MODEL_FEATURE_COLUMNS_PATH = os.getenv(
    "MODEL_FEATURE_COLUMNS_PATH",
    str(PROJECT_ROOT / "model" / "artifacts" / "feature_columns.json"),
)
LIVE_PREDICTION_ENABLED = os.getenv("LIVE_PREDICTION_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
LIVE_FEATURE_NEAREST_NEIGHBORS = int(os.getenv("LIVE_FEATURE_NEAREST_NEIGHBORS", "5"))


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


CORS_ALLOW_ORIGINS = _csv_env(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
)
CORS_ALLOW_ORIGIN_REGEX = os.getenv(
    "CORS_ALLOW_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
)
