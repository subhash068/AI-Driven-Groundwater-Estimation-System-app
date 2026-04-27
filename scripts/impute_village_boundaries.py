"""Non-destructive village boundary enrichment pipeline.

The raw GeoJSON remains immutable. This script writes an enriched derivative
with provenance and quality metadata so downstream layers can trust the output
without guessing how each value was produced.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import shape
from sklearn.impute import SimpleImputer
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor, NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from scripts.data_contract import (
    CONTRACT_VERSION,
    ENRICHED_LAYER,
    IMPUTED_STATISTICAL,
    MISSING,
    OBSERVED,
    QUALITY_FLAG_IMPUTED,
    QUALITY_FLAG_MISSING,
    QUALITY_FLAG_ZERO_ONLY,
    build_field_provenance,
    compute_quality_score,
    ensure_distinct_paths,
    is_missing_like,
    provenance_status_from_source,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "frontend" / "public" / "data" / "village_boundaries.geojson"
DEFAULT_OUTPUT = ROOT / "frontend" / "public" / "data" / "village_boundaries_imputed.geojson"
DEFAULT_REPORT = ROOT / "output" / "village_boundaries_imputation_report.json"

EARTH_RADIUS_KM = 6371.0088
FULL_SERIES_START = pd.Timestamp("1998-01-01")
TAIL_SERIES_LENGTH = 24
IDW_NEIGHBORS = 5
SERIES_NEIGHBORS = 8
KNN_NEIGHBORS = 7

MISSING_TOKENS = {"", "none", "null", "na", "n/a", "nan", "unknown", "missing", "undefined", "-"}
TEXT_PLACEHOLDER_TOKENS = {"", "none", "null", "na", "n/a", "unknown", "undefined", "missing", "-"}

SERIES_FIELDS = ("monthly_depths_full", "monthly_depths")
SERIES_LABEL_FIELDS = ("monthly_depths_full_dates", "monthly_depths_dates")
SCALAR_DERIVED_FIELDS = (
    "depth",
    "actual_last_month",
    "target_last_month",
    "long_term_avg",
    "trend_slope",
    "seasonal_variation",
    "available_years",
)
SPATIAL_NUMERIC_FIELDS = (
    "obs_elevation_msl_mean",
    "obs_total_depth_m",
    "avg_bore_depth_m",
    "avg_pump_capacity_hp",
)
CATEGORICAL_FIELDS = (
    "aquifer_code",
    "aquifer_class",
    "dominant_irrigation",
    "geomorphology",
)
ZERO_AS_MISSING_DEFAULT = {"avg_bore_depth_m", "avg_pump_capacity_hp", "obs_total_depth_m"}

PREDICTOR_FIELDS = (
    "centroid_lat",
    "centroid_lon",
    "depth",
    "actual_last_month",
    "target_last_month",
    "long_term_avg",
    "trend_slope",
    "seasonal_variation",
    "obs_elevation_msl_mean",
    "obs_total_depth_m",
    "avg_bore_depth_m",
    "avg_pump_capacity_hp",
    "wells_total",
    "pumping_functioning_wells",
    "pumping_estimated_draft_ha_m",
    "water_pct",
    "trees_pct",
    "flooded_vegetation_pct",
    "crops_pct",
    "built_area_pct",
    "bare_ground_pct",
    "rangeland_pct",
    "water_pct_2011",
    "trees_pct_2011",
    "flooded_vegetation_pct_2011",
    "crops_pct_2011",
    "built_area_pct_2011",
    "bare_ground_pct_2011",
    "rangeland_pct_2011",
    "water_pct_2021",
    "trees_pct_2021",
    "flooded_vegetation_pct_2021",
    "crops_pct_2021",
    "built_area_pct_2021",
    "bare_ground_pct_2021",
    "rangeland_pct_2021",
)


@dataclass
class FieldSummary:
    field: str
    changed_rows: int = 0
    original_missing_rows: int = 0
    source_counts: Counter[str] | None = None
    confidence_values: list[float] | None = None
    notes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.source_counts is None:
            self.source_counts = Counter()
        if self.confidence_values is None:
            self.confidence_values = []
        if self.notes is None:
            self.notes = []

    def record(self, source: str, confidence: float | None, changed: bool) -> None:
        self.source_counts[source] += 1
        if confidence is not None and math.isfinite(confidence):
            self.confidence_values.append(float(confidence))
        if changed:
            self.changed_rows += 1

    def as_dict(self) -> dict[str, Any]:
        confidences = self.confidence_values or []
        return {
            "field": self.field,
            "changed_rows": self.changed_rows,
            "original_missing_rows": self.original_missing_rows,
            "source_counts": dict(self.source_counts),
            "confidence_mean": round(float(mean(confidences)), 4) if confidences else None,
            "confidence_min": round(float(min(confidences)), 4) if confidences else None,
            "confidence_max": round(float(max(confidences)), 4) if confidences else None,
            "notes": list(self.notes),
        }


def _log(message: str) -> None:
    print(message)


def _is_placeholder_text(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in TEXT_PLACEHOLDER_TOKENS
    return False


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numeric) else float(numeric)


def _to_int(value: Any) -> int | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    try:
        return int(round(numeric))
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_series_value(value: Any) -> list[float | None]:
    if value is None:
        return []
    raw: Any = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            raw = ast.literal_eval(text)
        except Exception:
            try:
                raw = json.loads(text)
            except Exception:
                return []
    if not isinstance(raw, (list, tuple)):
        return []
    parsed: list[float | None] = []
    for item in raw:
        numeric = _to_float(item)
        parsed.append(numeric)
    return parsed


def _parse_label_value(value: Any) -> list[str]:
    if value is None:
        return []
    raw: Any = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            raw = ast.literal_eval(text)
        except Exception:
            try:
                raw = json.loads(text)
            except Exception:
                return []
    if not isinstance(raw, (list, tuple)):
        return []
    parsed: list[str] = []
    for item in raw:
        parsed.append("" if item is None else str(item).strip())
    return parsed


def _series_to_json(values: list[float | None]) -> list[float | None]:
    return [None if value is None else float(value) for value in values]


def _normalize_series_length(values: list[float | None], expected_len: int) -> list[float | None]:
    seq = list(values)
    if expected_len <= 0:
        return seq
    if len(seq) > expected_len:
        return seq[-expected_len:]
    if len(seq) < expected_len:
        return [None] * (expected_len - len(seq)) + seq
    return seq


def _interpolate_inside(values: list[float | None]) -> list[float | None]:
    series = pd.Series(values, dtype="float64")
    interpolated = series.interpolate(limit_area="inside")
    return [None if pd.isna(value) else float(value) for value in interpolated.tolist()]


def _month_sequence(start: pd.Timestamp, length: int) -> list[str]:
    labels: list[str] = []
    current = start
    for _ in range(length):
        labels.append(current.strftime("%Y-%m"))
        current = current + pd.offsets.MonthBegin(1)
    return labels


def _resolve_label_sequence(
    records: list[dict[str, Any]],
    field: str,
    expected_len: int,
    default_labels: list[str],
) -> list[str]:
    for record in records:
        parsed = _parse_label_value(record.get(field))
        if len(parsed) == expected_len and any(parsed):
            return parsed
    return list(default_labels)


def _feature_centroid(feature: dict[str, Any]) -> tuple[float, float]:
    props = feature.get("properties", {}) or {}
    lat = _to_float(props.get("centroid_lat"))
    lon = _to_float(props.get("centroid_lon"))
    if lat is not None and lon is not None:
        return lat, lon
    geometry = feature.get("geometry")
    if geometry:
        try:
            centroid = shape(geometry).centroid
            return float(centroid.y), float(centroid.x)
        except Exception:
            pass
    return 15.91, 79.74


def _build_neighbor_index(coords: list[tuple[float, float]], neighbor_count: int) -> tuple[np.ndarray, np.ndarray]:
    lat_lon = np.radians(np.asarray([(lat, lon) for lat, lon in coords], dtype=float))
    n_neighbors = min(len(lat_lon), neighbor_count + 1)
    nn = NearestNeighbors(n_neighbors=n_neighbors, metric="haversine")
    nn.fit(lat_lon)
    distances, indices = nn.kneighbors(lat_lon)
    return distances * EARTH_RADIUS_KM, indices


def _weighted_mean(values: list[float], distances: list[float]) -> float | None:
    if not values:
        return None
    clean_distances = [max(float(distance), 1e-6) for distance in distances]
    weights = [1.0 / distance for distance in clean_distances]
    denom = sum(weights)
    if denom <= 0:
        return None
    return float(sum(value * weight for value, weight in zip(values, weights, strict=False)) / denom)


def _weighted_mode(values: list[Any], distances: list[float]) -> tuple[Any | None, float | None]:
    if not values:
        return None, None
    bucket: dict[Any, float] = defaultdict(float)
    for value, distance in zip(values, distances, strict=False):
        if _is_placeholder_text(value):
            continue
        weight = 1.0 / max(float(distance), 1e-6)
        bucket[value] += weight
    if not bucket:
        return None, None
    selected, score = max(bucket.items(), key=lambda item: item[1])
    total = sum(bucket.values())
    confidence = float(score / total) if total > 0 else None
    return selected, confidence


def _derived_series_metrics(values: list[float | None], labels: list[str]) -> dict[str, Any]:
    finite_points = [(idx, float(value)) for idx, value in enumerate(values) if value is not None and math.isfinite(value)]
    if not finite_points:
        return {
            "depth": None,
            "actual_last_month": None,
            "target_last_month": None,
            "long_term_avg": None,
            "trend_slope": None,
            "seasonal_variation": None,
            "available_years": [],
        }

    finite_indices = np.asarray([point[0] for point in finite_points], dtype=float)
    finite_values = np.asarray([point[1] for point in finite_points], dtype=float)
    depth = float(finite_values[-1])
    long_term_avg = float(np.mean(finite_values))
    trend_slope = float(np.polyfit(finite_indices, finite_values, 1)[0]) if finite_values.size >= 2 else None

    month_buckets: dict[int, list[float]] = defaultdict(list)
    available_years: set[int] = set()
    for label, value in zip(labels, values, strict=False):
        if value is None or not math.isfinite(value):
            continue
        parsed = pd.to_datetime(label, errors="coerce")
        if pd.isna(parsed):
            continue
        available_years.add(int(parsed.year))
        month_buckets[int(parsed.month)].append(float(value))
    seasonal_variation = None
    if len(month_buckets) >= 2:
        monthly_means = [float(np.mean(bucket)) for bucket in month_buckets.values() if bucket]
        if len(monthly_means) >= 2:
            seasonal_variation = float(np.std(monthly_means))

    return {
        "depth": depth,
        "actual_last_month": depth,
        "target_last_month": depth,
        "long_term_avg": long_term_avg,
        "trend_slope": trend_slope,
        "seasonal_variation": seasonal_variation,
        "available_years": sorted(available_years),
    }


def _assign_if_changed(record: dict[str, Any], field: str, new_value: Any, original_value: Any) -> bool:
    changed = new_value != original_value
    if changed:
        if f"{field}_original" not in record:
            record[f"{field}_original"] = original_value
        record[field] = new_value
    return changed


def _store_resolved(
    record: dict[str, Any],
    field: str,
    new_value: Any,
    original_value: Any,
    *,
    source: str | None = None,
    confidence: float | None = None,
) -> bool:
    changed = new_value != original_value
    if changed:
        if f"{field}_original" not in record:
            record[f"{field}_original"] = deepcopy(original_value)
        record[field] = new_value
        record[f"{field}_imputed"] = True
        if source is not None:
            record[f"{field}_source"] = source
        if confidence is not None and math.isfinite(confidence):
            record[f"{field}_confidence"] = round(float(confidence), 4)
    else:
        record[field] = new_value
    return changed


def _build_numeric_frame(records: list[dict[str, Any]], target_field: str | None = None) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    for column in PREDICTOR_FIELDS:
        if column in frame.columns and column != target_field:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "centroid_lat" not in frame.columns:
        frame["centroid_lat"] = np.nan
    if "centroid_lon" not in frame.columns:
        frame["centroid_lon"] = np.nan
    return frame


def _idw_regress(
    field: str,
    records: list[dict[str, Any]],
    coords: list[tuple[float, float]],
    neighbor_distances: np.ndarray,
    neighbor_indices: np.ndarray,
    zero_as_missing: set[str],
) -> tuple[list[Any], FieldSummary, list[str], list[float | None]]:
    summary = FieldSummary(field=field)
    frame = _build_numeric_frame(records, target_field=field)
    original: list[float | None] = []
    missing_mask: list[bool] = []
    observed_indices: list[int] = []
    for idx, value in enumerate(frame.get(field, pd.Series([None] * len(frame)))):
        numeric = _to_float(value)
        if numeric is None:
            original.append(None)
            missing_mask.append(True)
            summary.original_missing_rows += 1
            continue
        if field in zero_as_missing and numeric == 0.0:
            original.append(None)
            missing_mask.append(True)
            summary.original_missing_rows += 1
            continue
        original.append(float(numeric))
        missing_mask.append(False)
        observed_indices.append(idx)

    if not any(missing_mask):
        summary.notes.append("no_missing_values")
        return original, summary, ["original" for _ in original], [1.0 for _ in original]

    if not observed_indices:
        summary.notes.append("no_observed_values")
        return original, summary, ["unresolved" if flag else "original" for flag in missing_mask], [None if flag else 1.0 for flag in missing_mask]

    values = original[:]
    row_sources = ["original" if not is_missing else "unresolved" for is_missing in missing_mask]
    row_confidences: list[float | None] = [1.0 if not is_missing else None for is_missing in missing_mask]

    knn_value = None
    knn_confidence = None
    use_knn = len(observed_indices) >= 5
    if use_knn:
        predictors = frame[list(PREDICTOR_FIELDS)]
        predictors = predictors.drop(columns=[field], errors="ignore")
        predictor_frame = predictors.apply(pd.to_numeric, errors="coerce")
        train_x = predictor_frame.iloc[observed_indices]
        train_y = np.asarray([original[idx] for idx in observed_indices], dtype=float)
        query_x = predictor_frame
        knn_model = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("knn", KNeighborsRegressor(n_neighbors=min(KNN_NEIGHBORS, len(observed_indices)), weights="distance")),
            ]
        )
        try:
            knn_model.fit(train_x, train_y)
            knn_value = knn_model.predict(query_x)
            knn_distances = knn_model.named_steps["knn"].kneighbors(
                knn_model.named_steps["scaler"].transform(
                    knn_model.named_steps["imputer"].transform(query_x)
                )
            )[0]
            knn_confidence = 1.0 / (1.0 + np.nanmean(knn_distances, axis=1))
        except Exception:
            knn_value = None
            knn_confidence = None

    for idx, is_missing in enumerate(missing_mask):
        if not is_missing:
            continue
        # Try IDW first.
        candidate_values: list[float] = []
        candidate_distances: list[float] = []
        for neighbor_pos, neighbor_index in enumerate(neighbor_indices[idx][1:], start=1):
            neighbor_value = original[neighbor_index]
            if neighbor_value is None:
                continue
            candidate_values.append(float(neighbor_value))
            candidate_distances.append(float(neighbor_distances[idx][neighbor_pos]))
            if len(candidate_values) >= IDW_NEIGHBORS:
                break

        chosen_value = None
        chosen_source = "idw"
        chosen_confidence = None
        if candidate_values:
            chosen_value = _weighted_mean(candidate_values, candidate_distances)
            avg_distance = float(np.mean(candidate_distances)) if candidate_distances else None
            if avg_distance is not None:
                distance_factor = math.exp(-avg_distance / 15.0)
                spread_factor = 1.0
                if len(candidate_values) >= 2 and mean(candidate_values) != 0:
                    spread_factor = 1.0 / (1.0 + (pstdev(candidate_values) / (abs(mean(candidate_values)) + 1e-6)))
                chosen_confidence = float(np.clip(0.2 + 0.6 * distance_factor + 0.2 * spread_factor, 0.05, 0.99))
            else:
                chosen_confidence = 0.55

        if chosen_value is None and knn_value is not None:
            chosen_source = "knn"
            chosen_value = float(knn_value[idx])
            chosen_confidence = float(np.clip(knn_confidence[idx] if knn_confidence is not None else 0.6, 0.05, 0.95))
        elif chosen_value is not None and knn_value is not None:
            knn_weight = float(np.clip(knn_confidence[idx] if knn_confidence is not None else 0.5, 0.05, 0.95))
            idw_weight = float(np.clip(chosen_confidence if chosen_confidence is not None else 0.5, 0.05, 0.99))
            chosen_value = float((chosen_value * idw_weight + float(knn_value[idx]) * knn_weight) / (idw_weight + knn_weight))
            chosen_source = "idw+knn"
            chosen_confidence = float((idw_weight + knn_weight) / 2.0)

        if chosen_value is None:
            continue

        values[idx] = float(chosen_value)
        row_sources[idx] = chosen_source
        row_confidences[idx] = float(chosen_confidence if chosen_confidence is not None else 0.55)
        summary.record(chosen_source, float(chosen_confidence if chosen_confidence is not None else 0.55), True)

    summary.original_missing_rows = int(sum(missing_mask))
    return values, summary, row_sources, row_confidences


def _idw_classify(
    field: str,
    records: list[dict[str, Any]],
    coords: list[tuple[float, float]],
    neighbor_distances: np.ndarray,
    neighbor_indices: np.ndarray,
) -> tuple[list[Any], FieldSummary, list[str], list[float | None]]:
    summary = FieldSummary(field=field)
    values = [record.get(field) for record in records]
    observed = [not _is_placeholder_text(value) for value in values]
    summary.original_missing_rows = int(sum(1 for flag in observed if not flag))

    if summary.original_missing_rows == 0:
        summary.notes.append("no_missing_values")
        return values, summary, ["original" for _ in values], [1.0 for _ in values]

    observed_indices = [idx for idx, flag in enumerate(observed) if flag]
    if not observed_indices:
        summary.notes.append("no_observed_values")
        return values, summary, ["unresolved" if not flag else "original" for flag in observed], [None if not flag else 1.0 for flag in observed]

    frame = _build_numeric_frame(records)
    predictors = frame[list(PREDICTOR_FIELDS)].apply(pd.to_numeric, errors="coerce")
    train_x = predictors.iloc[observed_indices]
    train_y = np.asarray([values[idx] for idx in observed_indices], dtype=object)
    query_x = predictors
    classifier = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("knn", KNeighborsClassifier(n_neighbors=min(KNN_NEIGHBORS, len(observed_indices)), weights="distance")),
        ]
    )

    knn_prediction = None
    knn_confidence = None
    try:
        classifier.fit(train_x, train_y)
        knn_prediction = classifier.predict(query_x)
        knn_distances = classifier.named_steps["knn"].kneighbors(
            classifier.named_steps["scaler"].transform(
                classifier.named_steps["imputer"].transform(query_x)
            )
        )[0]
        knn_confidence = 1.0 / (1.0 + np.nanmean(knn_distances, axis=1))
    except Exception:
        knn_prediction = None
        knn_confidence = None

    resolved = values[:]
    row_sources = ["original" if flag else "unresolved" for flag in observed]
    row_confidences: list[float | None] = [1.0 if flag else None for flag in observed]
    for idx, flag in enumerate(observed):
        if flag:
            continue
        candidate_values: list[str] = []
        candidate_distances: list[float] = []
        for neighbor_pos, neighbor_index in enumerate(neighbor_indices[idx][1:], start=1):
            observed_index = neighbor_index
            neighbor_value = values[observed_index]
            if _is_placeholder_text(neighbor_value):
                continue
            candidate_values.append(str(neighbor_value))
            candidate_distances.append(float(neighbor_distances[idx][neighbor_pos]))
            if len(candidate_values) >= SERIES_NEIGHBORS:
                break

        chosen_value: Any | None = None
        chosen_confidence: float | None = None
        chosen_source = "neighbor_vote"
        if candidate_values:
            chosen_value, chosen_confidence = _weighted_mode(candidate_values, candidate_distances)
        if chosen_value is None and knn_prediction is not None:
            chosen_value = str(knn_prediction[idx])
            chosen_confidence = float(np.clip(knn_confidence[idx] if knn_confidence is not None else 0.6, 0.05, 0.95))
            chosen_source = "knn"

        if chosen_value is None:
            continue

        resolved[idx] = chosen_value
        row_sources[idx] = chosen_source
        row_confidences[idx] = float(chosen_confidence if chosen_confidence is not None else 0.6)
        summary.record(chosen_source, chosen_confidence, True)

    return resolved, summary, row_sources, row_confidences


def _resolve_series_field(
    field: str,
    records: list[dict[str, Any]],
    label_field: str,
    expected_len: int,
    default_labels: list[str],
    coords: list[tuple[float, float]],
    neighbor_distances: np.ndarray,
    neighbor_indices: np.ndarray,
) -> tuple[list[list[float | None]], list[str], FieldSummary, list[str], list[float | None]]:
    summary = FieldSummary(field=field)
    raw_series = [_parse_series_value(record.get(field)) for record in records]
    raw_labels = [_parse_label_value(record.get(label_field)) for record in records]
    normalized_series = [_normalize_series_length(series, expected_len) for series in raw_series]

    # First pass: fill internal gaps only.
    staged_series = [_interpolate_inside(series) for series in normalized_series]

    full_labels = _resolve_label_sequence(records, "monthly_depths_full_dates", len(default_labels), default_labels)
    if field == "monthly_depths":
        label_values = _resolve_label_sequence(records, label_field, expected_len, full_labels[-expected_len:])
    else:
        label_values = _resolve_label_sequence(records, label_field, expected_len, default_labels)

    # Column means from the staged rows, used as a final fallback.
    global_means: list[float | None] = []
    for col_idx in range(expected_len):
        col_values = [row[col_idx] for row in staged_series if col_idx < len(row) and row[col_idx] is not None]
        global_means.append(float(mean(col_values)) if col_values else None)

    final_series: list[list[float | None]] = []
    row_sources: list[str] = []
    row_confidences: list[float | None] = []
    confidences: list[float] = []
    for row_idx, staged in enumerate(staged_series):
        row = staged[:]
        original = normalized_series[row_idx]
        original_non_missing = sum(1 for value in original if value is not None)
        missing_positions = [pos for pos, value in enumerate(row) if value is None]
        fill_distances: list[float] = []
        used_neighbor_fill = False
        if missing_positions:
            for pos in missing_positions:
                neighbor_values: list[float] = []
                neighbor_dists: list[float] = []
                for neighbor_order, neighbor_index in enumerate(neighbor_indices[row_idx][1:], start=1):
                    candidate_row = staged_series[neighbor_index]
                    if pos >= len(candidate_row):
                        continue
                    candidate_value = candidate_row[pos]
                    if candidate_value is None:
                        continue
                    neighbor_values.append(float(candidate_value))
                    neighbor_dists.append(float(neighbor_distances[row_idx][neighbor_order]))
                    if len(neighbor_values) >= SERIES_NEIGHBORS:
                        break
                if neighbor_values:
                    row[pos] = _weighted_mean(neighbor_values, neighbor_dists)
                    fill_distances.extend(neighbor_dists)
                    used_neighbor_fill = True
                elif global_means[pos] is not None:
                    row[pos] = float(global_means[pos])
        row = _interpolate_inside(row)
        if any(value is None for value in row):
            for pos, value in enumerate(row):
                if value is None and global_means[pos] is not None:
                    row[pos] = float(global_means[pos])
        if any(value is None for value in row):
            remaining = [value for value in row if value is not None]
            if remaining:
                fill_value = float(mean(remaining))
                row = [fill_value if value is None else value for value in row]
                used_neighbor_fill = True
        if not row:
            row = [None] * expected_len

        if used_neighbor_fill:
            distance_factor = math.exp(-(float(mean(fill_distances)) if fill_distances else 0.0) / 20.0)
        else:
            distance_factor = 1.0
        coverage_factor = original_non_missing / expected_len if expected_len else 0.0
        if original_non_missing == 0:
            confidence = float(np.clip(0.35 + 0.45 * distance_factor, 0.05, 0.9))
        else:
            confidence = float(np.clip(0.3 + 0.5 * coverage_factor + 0.2 * distance_factor, 0.05, 0.99))
        row_source = "original" if missing_positions == [] else ("idw_series" if used_neighbor_fill else "linear_interpolation")
        summary.record(row_source, confidence, bool(missing_positions))
        confidences.append(confidence)
        row_sources.append(row_source)
        row_confidences.append(confidence if missing_positions else 1.0)
        final_series.append([None if value is None else float(value) for value in row])

    summary.original_missing_rows = int(sum(1 for row in normalized_series if any(value is None for value in row) or not row))
    if not summary.source_counts:
        summary.source_counts["original"] = len(records)
    return final_series, label_values, summary, row_sources, row_confidences


def _find_zero_only_fields(records: list[dict[str, Any]], fields: list[str]) -> list[str]:
    zero_only: list[str] = []
    for field in fields:
        numeric_values = [_to_float(record.get(field)) for record in records]
        numeric_values = [value for value in numeric_values if value is not None]
        if numeric_values and all(value == 0.0 for value in numeric_values):
            zero_only.append(field)
    return zero_only


PROVENANCE_EXCLUDED_KEYS = {
    "type",
    "geometry",
    "provenance",
    "data_layer",
    "data_contract_version",
    "data_quality_score",
    "data_quality_breakdown",
    "data_quality_flags",
}
PROVENANCE_EXCLUDED_SUFFIXES = ("_original", "_imputed", "_source", "_confidence")


def _is_provenance_metadata_key(key: str) -> bool:
    if not key:
        return True
    if key in PROVENANCE_EXCLUDED_KEYS:
        return True
    if key.startswith("_"):
        return True
    return key.endswith(PROVENANCE_EXCLUDED_SUFFIXES)


def _build_record_provenance(
    record: dict[str, Any],
    zero_only_fields: set[str],
) -> tuple[dict[str, dict[str, Any]], float, dict[str, Any]]:
    provenance: dict[str, dict[str, Any]] = {}

    for field, value in record.items():
        if _is_provenance_metadata_key(field):
            continue
        if field == "geometry":
            continue

        source = record.get(f"{field}_source")
        confidence = record.get(f"{field}_confidence")
        imputed = bool(record.get(f"{field}_imputed"))
        original_present = f"{field}_original" in record
        missing_like = is_missing_like(value)
        quality_flags: list[str] = []

        if field in zero_only_fields and _to_float(value) == 0.0:
            quality_flags.append(QUALITY_FLAG_ZERO_ONLY)
        if missing_like:
            quality_flags.append(QUALITY_FLAG_MISSING)
        if imputed:
            quality_flags.append(QUALITY_FLAG_IMPUTED)

        if missing_like:
            status = MISSING
        elif imputed:
            status = provenance_status_from_source(source, default=IMPUTED_STATISTICAL)
        else:
            status = OBSERVED

        provenance[field] = build_field_provenance(
            status=status,
            source=source,
            confidence=confidence,
            imputed=imputed,
            original_present=original_present,
            quality_flags=quality_flags,
        )

    score, breakdown = compute_quality_score(provenance)
    return provenance, score, breakdown


def impute_village_boundaries(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    zero_as_missing: set[str],
) -> dict[str, Any]:
    ensure_distinct_paths(input_path, output_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"Expected a GeoJSON FeatureCollection at {input_path}")

    features = [feature for feature in payload.get("features", []) if isinstance(feature, dict)]
    records = [deepcopy(feature.get("properties", {}) or {}) for feature in features]
    coords = [_feature_centroid(feature) for feature in features]
    neighbor_distances, neighbor_indices = _build_neighbor_index(coords, neighbor_count=SERIES_NEIGHBORS)

    full_labels = _resolve_label_sequence(
        records,
        "monthly_depths_full_dates",
        324,
        _month_sequence(FULL_SERIES_START, 324),
    )
    tail_labels = full_labels[-TAIL_SERIES_LENGTH:] if len(full_labels) >= TAIL_SERIES_LENGTH else _month_sequence(pd.Timestamp("2023-01-01"), TAIL_SERIES_LENGTH)
    original_full_series = [
        _normalize_series_length(_parse_series_value(record.get("monthly_depths_full")), len(full_labels))
        for record in records
    ]
    original_tail_series = [
        _normalize_series_length(_parse_series_value(record.get("monthly_depths")), TAIL_SERIES_LENGTH)
        for record in records
    ]
    full_series, full_labels, series_summary_full, full_sources, full_confidences = _resolve_series_field(
        "monthly_depths_full",
        records,
        "monthly_depths_full_dates",
        len(full_labels),
        full_labels,
        coords,
        neighbor_distances,
        neighbor_indices,
    )
    for idx, series in enumerate(full_series):
        _store_resolved(
            records[idx],
            "monthly_depths_full",
            _series_to_json(series),
            _series_to_json(original_full_series[idx]),
            source=full_sources[idx],
            confidence=full_confidences[idx],
        )
        _store_resolved(
            records[idx],
            "monthly_depths_full_dates",
            list(full_labels),
            _parse_label_value(records[idx].get("monthly_depths_full_dates")),
            source="derived_labels",
            confidence=1.0,
        )
        _store_resolved(
            records[idx],
            "available_years",
            sorted({int(label[:4]) for label in full_labels if len(label) >= 4 and label[:4].isdigit()}),
            records[idx].get("available_years"),
            source="derived_years",
            confidence=1.0,
        )

    tail_series = [series[-TAIL_SERIES_LENGTH:] if len(series) >= TAIL_SERIES_LENGTH else _normalize_series_length(series, TAIL_SERIES_LENGTH) for series in full_series]
    for idx, series in enumerate(tail_series):
        _store_resolved(
            records[idx],
            "monthly_depths",
            _series_to_json(series),
            _series_to_json(original_tail_series[idx]),
            source="derived_tail_series",
            confidence=full_confidences[idx],
        )
        _store_resolved(
            records[idx],
            "monthly_depths_dates",
            list(tail_labels),
            _parse_label_value(records[idx].get("monthly_depths_dates")),
            source="derived_labels",
            confidence=1.0,
        )

    derived_metrics = [_derived_series_metrics(series, full_labels) for series in full_series]
    for idx, metrics in enumerate(derived_metrics):
        for field in SCALAR_DERIVED_FIELDS:
            value = metrics.get(field)
            if value is None:
                continue
            current = records[idx].get(field)
            if _is_placeholder_text(current) or (field == "depth" and _to_float(current) is None):
                _store_resolved(
                    records[idx],
                    field,
                    value,
                    current,
                    source="derived_series",
                    confidence=full_confidences[idx],
                )

    field_summaries: dict[str, FieldSummary] = {
        "series_full": series_summary_full,
    }

    for field in SPATIAL_NUMERIC_FIELDS:
        resolved, summary, sources, confidences = _idw_regress(
            field=field,
            records=records,
            coords=coords,
            neighbor_distances=neighbor_distances,
            neighbor_indices=neighbor_indices,
            zero_as_missing=zero_as_missing,
        )
        field_summaries[field] = summary
        for idx, value in enumerate(resolved):
            if value is None:
                continue
            current = records[idx].get(field)
            if _to_float(current) is None or (field in zero_as_missing and _to_float(current) == 0.0):
                _store_resolved(
                    records[idx],
                    field,
                    float(value),
                    current,
                    source=sources[idx],
                    confidence=confidences[idx],
                )

    for field in CATEGORICAL_FIELDS:
        resolved, summary, sources, confidences = _idw_classify(
            field=field,
            records=records,
            coords=coords,
            neighbor_distances=neighbor_distances,
            neighbor_indices=neighbor_indices,
        )
        field_summaries[field] = summary
        for idx, value in enumerate(resolved):
            if _is_placeholder_text(records[idx].get(field)) and not _is_placeholder_text(value):
                _store_resolved(
                    records[idx],
                    field,
                    value,
                    records[idx].get(field),
                    source=sources[idx],
                    confidence=confidences[idx],
                )

    # Canonicalize the derived time-series helpers after the scalar/categorical fills.
    for idx, metrics in enumerate(derived_metrics):
        for field in ("depth", "actual_last_month", "target_last_month", "long_term_avg", "trend_slope", "seasonal_variation"):
            value = metrics.get(field)
            if value is None:
                continue
            if _is_placeholder_text(records[idx].get(field)):
                _store_resolved(
                    records[idx],
                    field,
                    value,
                    records[idx].get(field),
                    source="derived_series",
                    confidence=full_confidences[idx],
                )
        if not records[idx].get("available_years"):
            _store_resolved(
                records[idx],
                "available_years",
                metrics["available_years"],
                records[idx].get("available_years"),
                source="derived_years",
                confidence=1.0,
            )

    zero_only_fields = _find_zero_only_fields(records, [
        "clouds_pct",
        "clouds_pct_2011",
        "clouds_pct_2021",
        "snow_ice_pct",
        "snow_ice_pct_2011",
        "snow_ice_pct_2021",
    ])

    overall_status_counts: Counter[str] = Counter()
    overall_quality_flags: Counter[str] = Counter()
    quality_scores: list[float] = []

    for record in records:
        provenance, quality_score, quality_breakdown = _build_record_provenance(record, set(zero_only_fields))
        record["provenance"] = provenance
        record["data_layer"] = ENRICHED_LAYER
        record["data_contract_version"] = CONTRACT_VERSION
        record["data_quality_score"] = quality_score
        record["data_quality_breakdown"] = quality_breakdown
        record["data_quality_flags"] = sorted(quality_breakdown.get("quality_flag_counts", {}).keys())
        quality_scores.append(quality_score)
        overall_status_counts.update(quality_breakdown.get("status_counts", {}))
        overall_quality_flags.update(quality_breakdown.get("quality_flag_counts", {}))

    for feature, record in zip(features, records, strict=False):
        props = feature.setdefault("properties", {})
        props.clear()
        props.update(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "input": str(input_path),
        "output": str(output_path),
        "contract_version": CONTRACT_VERSION,
        "input_layer": "raw",
        "output_layer": ENRICHED_LAYER,
        "feature_count": len(features),
        "zero_as_missing_fields": sorted(zero_as_missing),
        "zero_only_fields": zero_only_fields,
        "field_summaries": {name: summary.as_dict() for name, summary in field_summaries.items()},
        "quality_summary": {
            "mean_score": round(float(mean(quality_scores)), 4) if quality_scores else None,
            "min_score": round(float(min(quality_scores)), 4) if quality_scores else None,
            "max_score": round(float(max(quality_scores)), 4) if quality_scores else None,
            "field_count": int(sum(overall_status_counts.values())),
            "status_counts": dict(overall_status_counts),
            "quality_flag_counts": dict(overall_quality_flags),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Non-destructive village boundary imputation pipeline")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input village boundary GeoJSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Derived GeoJSON output path")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Imputation report JSON path")
    parser.add_argument(
        "--zero-as-missing",
        type=str,
        default=",".join(sorted(ZERO_AS_MISSING_DEFAULT)),
        help="Comma-separated numeric fields where zero should be treated as missing",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    zero_as_missing = {field.strip() for field in str(args.zero_as_missing).split(",") if field.strip()}
    report = impute_village_boundaries(
        input_path=args.input,
        output_path=args.output,
        report_path=args.report,
        zero_as_missing=zero_as_missing,
    )
    _log(f"Saved derived GeoJSON to {args.output}")
    _log(f"Saved imputation report to {args.report}")
    _log(f"Features processed: {report['feature_count']}")


if __name__ == "__main__":
    main()
