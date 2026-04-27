"""Shared data-contract helpers for groundwater data layers.

The contract is intentionally small and reusable:

RAW -> RECONCILED -> ENRICHED -> CONSUMPTION

This module keeps the layer names, provenance statuses, and quality scoring in
one place so future pipeline code does not need to invent its own conventions.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

RAW_LAYER = "raw"
RECONCILED_LAYER = "reconciled"
ENRICHED_LAYER = "enriched"
CONSUMPTION_LAYER = "consumption"

CONTRACT_VERSION = "1.0"

OBSERVED = "observed"
TRANSFERRED_SPATIAL = "transferred_spatial"
IMPUTED_STATISTICAL = "imputed_statistical"
DERIVED_MODEL = "derived_model"
RECOVERED_EXTERNAL = "recovered_external"
MISSING = "missing"

MISSING_TOKENS = {"", "none", "null", "na", "n/a", "nan", "unknown", "missing", "undefined", "-"}
QUALITY_FLAG_ZERO_ONLY = "zero_only"
QUALITY_FLAG_MISSING = "missing"
QUALITY_FLAG_IMPUTED = "imputed"

STATUS_WEIGHTS = {
    OBSERVED: 1.0,
    RECOVERED_EXTERNAL: 0.85,
    TRANSFERRED_SPATIAL: 0.78,
    IMPUTED_STATISTICAL: 0.62,
    DERIVED_MODEL: 0.58,
    MISSING: 0.0,
}


def _coerce_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return float(numeric)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def is_missing_like(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_TOKENS
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return len(value) == 0
    return False


def provenance_status_from_source(source: Any, *, default: str = IMPUTED_STATISTICAL) -> str:
    text = str(source or "").strip().lower()
    if not text or text in {"original", "observed", "source"}:
        return OBSERVED
    if text in {"missing", "unresolved"}:
        return MISSING
    if "external" in text or "join" in text or "lookup" in text:
        return RECOVERED_EXTERNAL
    if text.startswith("neighbor") or text == "transferred_spatial":
        return TRANSFERRED_SPATIAL
    if text.startswith("derived") and ("model" in text or "forecast" in text or "prediction" in text):
        return DERIVED_MODEL
    if text.startswith("derived"):
        return IMPUTED_STATISTICAL
    if "idw" in text or "knn" in text or "interpolation" in text or "series" in text:
        return IMPUTED_STATISTICAL
    return default


def build_field_provenance(
    *,
    status: str,
    source: Any | None = None,
    confidence: Any | None = None,
    imputed: bool = False,
    original_present: bool = False,
    quality_flags: Iterable[str] | None = None,
) -> dict[str, Any]:
    flags = sorted({str(flag).strip() for flag in (quality_flags or []) if str(flag).strip()})
    normalized_confidence = _coerce_float(confidence)
    normalized_source = str(source or "").strip() or ("original" if status == OBSERVED else status)
    payload: dict[str, Any] = {
        "status": status,
        "source": normalized_source,
        "imputed": bool(imputed),
        "original_present": bool(original_present),
        "quality_flags": flags,
    }
    if normalized_confidence is not None:
        payload["confidence"] = round(_clamp01(normalized_confidence), 4)
    return payload


def compute_quality_score(provenance_map: Mapping[str, Mapping[str, Any]]) -> tuple[float, dict[str, Any]]:
    if not provenance_map:
        return 0.0, {
            "field_count": 0,
            "status_counts": {},
            "quality_flag_counts": {},
        }

    status_counts: Counter[str] = Counter()
    quality_flag_counts: Counter[str] = Counter()
    weighted_total = 0.0
    field_count = 0

    for meta in provenance_map.values():
        status = str(meta.get("status") or MISSING)
        confidence = _coerce_float(meta.get("confidence"))
        flags = [str(flag).strip() for flag in (meta.get("quality_flags") or []) if str(flag).strip()]

        weight = STATUS_WEIGHTS.get(status, 0.0)
        if confidence is not None:
            weight *= 0.6 + (0.4 * _clamp01(confidence))
        if QUALITY_FLAG_ZERO_ONLY in flags:
            weight *= 0.9

        weighted_total += weight
        field_count += 1
        status_counts[status] += 1
        for flag in flags:
            quality_flag_counts[flag] += 1

    score = round(max(0.0, min(1.0, weighted_total / field_count)), 4) if field_count else 0.0
    return score, {
        "field_count": field_count,
        "status_counts": dict(status_counts),
        "quality_flag_counts": dict(quality_flag_counts),
    }


def ensure_distinct_paths(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must be different to preserve the raw layer.")
