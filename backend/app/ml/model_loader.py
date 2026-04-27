from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

import xgboost as xgb

from ..config import MODEL_ARTIFACT_PATH, MODEL_FEATURE_COLUMNS_PATH


_LOCK = Lock()
_MODEL: xgb.XGBRegressor | None = None
_FEATURE_COLUMNS: list[str] | None = None


def _read_feature_columns(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Feature column file is not a list: {path}")
    columns = [str(item) for item in payload if str(item).strip()]
    if not columns:
        raise ValueError(f"Feature column file is empty: {path}")
    return columns


def get_feature_columns() -> list[str]:
    global _FEATURE_COLUMNS
    if _FEATURE_COLUMNS is None:
        with _LOCK:
            if _FEATURE_COLUMNS is None:
                feature_path = Path(MODEL_FEATURE_COLUMNS_PATH)
                if not feature_path.exists():
                    raise FileNotFoundError(f"Feature column artifact not found: {feature_path}")
                _FEATURE_COLUMNS = _read_feature_columns(feature_path)
    return list(_FEATURE_COLUMNS)


def get_model() -> xgb.XGBRegressor:
    global _MODEL
    if _MODEL is None:
        with _LOCK:
            if _MODEL is None:
                model_path = Path(MODEL_ARTIFACT_PATH)
                if not model_path.exists():
                    raise FileNotFoundError(f"Model artifact not found: {model_path}")
                model = xgb.XGBRegressor()
                model.load_model(str(model_path))
                _MODEL = model
    return _MODEL

