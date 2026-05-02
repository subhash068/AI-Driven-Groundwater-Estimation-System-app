from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
import xgboost as xgb


FEATURE_COLUMNS = [
    "rainfall",
    "gw_lag_1",
    "gw_lag_2",
    "gw_lag_3",
    "rainfall_lag_1m",
    "rainfall_lag_3m",
    "rainfall_lag_6m",
    "rainfall_3m_sum",
    "rainfall_6m_sum",
    "rainfall_anomaly",
    "effective_recharge",
    "seasonal_phase_enc",
    "distance_to_canal_km",
    "distance_to_stream_km",
    "distance_to_tank_km",
    "aquifer_type_enc",
    "lulc_class_enc",
    "pumping_data",
    "nearest_piezometer_distance_km",
    "nearest_piezometer_groundwater",
    "average_groundwater_within_10km",
    "weighted_groundwater_idw",
    "nearby_groundwater_std_10km",
    "nearby_piezometer_count_10km",
    "lag_availability",
]
TARGET_COLUMN = "groundwater_level"


def _safe_mape(y_true: pd.Series, y_pred: np.ndarray) -> float:
    yt = pd.to_numeric(y_true, errors="coerce").to_numpy(dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(yt) & np.isfinite(yp) & (np.abs(yt) >= 0.5)
    if not np.any(mask):
        return float("nan")
    return float(np.mean(np.abs((yt[mask] - yp[mask]) / yt[mask])))


@dataclass
class ModelOutput:
    village_month_predictions: pd.DataFrame
    metrics: dict[str, float]
    feature_importance: pd.DataFrame


def _knn_blend_per_month(frame: pd.DataFrame, pred_col: str, k: int = 5) -> pd.Series:
    from sklearn.neighbors import NearestNeighbors
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    if "village_x" not in frame.columns or "village_y" not in frame.columns:
        return frame[pred_col]

    for month, month_idx in frame.groupby("date").groups.items():
        idx = list(month_idx)
        month_df = frame.loc[idx]
        coords = np.column_stack([
            pd.to_numeric(month_df["village_x"], errors="coerce").fillna(0).to_numpy(dtype=float),
            pd.to_numeric(month_df["village_y"], errors="coerce").fillna(0).to_numpy(dtype=float)
        ])
        pred = pd.to_numeric(month_df[pred_col], errors="coerce").to_numpy(dtype=float)
        
        if len(month_df) <= 1:
            out.loc[idx] = pred
            continue

        # Use NearestNeighbors which is much more memory efficient for large sets
        nn = NearestNeighbors(n_neighbors=min(k + 1, len(month_df)))
        nn.fit(coords)
        distances, indices = nn.kneighbors(coords)
        
        for i, row_idx in enumerate(idx):
            # The first neighbor is the point itself (distance 0)
            nbr_indices = indices[i][1:]
            if len(nbr_indices) > 0:
                nbr_mean = float(np.nanmean(pred[nbr_indices]))
                out.loc[row_idx] = 0.7 * float(pred[i]) + 0.3 * nbr_mean
            else:
                out.loc[row_idx] = float(pred[i])
    return out


def train_and_predict_xgboost(features: pd.DataFrame) -> ModelOutput:
    frame = features.copy()
    frame["has_piezometer"] = pd.to_numeric(frame.get("has_piezometer", 0), errors="coerce").fillna(0).astype(int)
    frame[TARGET_COLUMN] = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    frame["weighted_groundwater_idw"] = pd.to_numeric(frame["weighted_groundwater_idw"], errors="coerce")
    frame["idw_baseline"] = frame["weighted_groundwater_idw"].fillna(frame["weighted_groundwater_idw"].median()).fillna(0.0)
    frame["residual_target"] = frame[TARGET_COLUMN] - frame["idw_baseline"]

    # Region-based normalization by aquifer zone.
    aquifer_key = frame["aquifer_type"].fillna("Unknown").astype(str) if "aquifer_type" in frame.columns else pd.Series("Unknown", index=frame.index)
    train_mask = (frame["has_piezometer"] == 1) & frame["residual_target"].notna()
    zone_stats = (
        frame.loc[train_mask]
        .assign(_zone=aquifer_key[train_mask])
        .groupby("_zone", as_index=True)["residual_target"]
        .agg(["mean", "std"])
    )
    zone_mean = zone_stats["mean"].to_dict()
    zone_std = zone_stats["std"].replace(0, np.nan).fillna(1.0).to_dict()

    frame["_zone"] = aquifer_key
    frame["zone_residual_mean"] = frame["_zone"].map(zone_mean).fillna(float(frame.loc[train_mask, "residual_target"].mean()))
    frame["zone_residual_std"] = frame["_zone"].map(zone_std).fillna(1.0)
    frame["residual_target_norm"] = (frame["residual_target"] - frame["zone_residual_mean"]) / frame["zone_residual_std"]

    train_frame = frame[(frame["has_piezometer"] == 1) & frame["residual_target_norm"].notna()].copy()
    if train_frame.empty:
        raise ValueError("No observed groundwater target rows available for training.")

    X = train_frame[FEATURE_COLUMNS].copy()
    y = train_frame["residual_target_norm"].copy()
    sample_weight = 1.0 / (1.0 + pd.to_numeric(train_frame["nearest_piezometer_distance_km"], errors="coerce").fillna(10.0))

    X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
        X, y, sample_weight, test_size=0.2, random_state=42
    )
    # Convert to numpy explicitly to avoid interface issues on Python 3.13/Windows
    X_train_np = X_train.to_numpy(dtype=float)
    y_train_np = y_train.to_numpy(dtype=float)
    w_train_np = w_train.to_numpy(dtype=float)

    model = xgb.XGBRegressor(
        n_estimators=50,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        objective="reg:squarederror",
    )
    model.fit(X_train_np, y_train_np, sample_weight=w_train_np)

    y_test_pred_norm = model.predict(X_test)
    test_zone_mean = train_frame.loc[X_test.index, "zone_residual_mean"].to_numpy(dtype=float)
    test_zone_std = train_frame.loc[X_test.index, "zone_residual_std"].to_numpy(dtype=float)
    y_test_residual = y_test.to_numpy(dtype=float) * test_zone_std + test_zone_mean
    y_test_true = train_frame.loc[X_test.index, "residual_target"].to_numpy(dtype=float) + train_frame.loc[X_test.index, "idw_baseline"].to_numpy(dtype=float)
    y_test_pred = y_test_pred_norm * test_zone_std + test_zone_mean + train_frame.loc[X_test.index, "idw_baseline"].to_numpy(dtype=float)
    metrics = {
        "mae": float(mean_absolute_error(y_test_true, y_test_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_test_true, y_test_pred))),
        "r2": float(r2_score(y_test_true, y_test_pred)),
        "mape": _safe_mape(pd.Series(y_test_true), y_test_pred),
    }

    frame["predicted_residual_norm"] = model.predict(frame[FEATURE_COLUMNS])
    frame["predicted_residual"] = (
        frame["predicted_residual_norm"] * frame["zone_residual_std"] + frame["zone_residual_mean"]
    )
    frame["predicted_groundwater_residual_raw"] = frame["idw_baseline"] + frame["predicted_residual"]
    frame["predicted_groundwater_xgb"] = _knn_blend_per_month(frame, "predicted_groundwater_residual_raw", k=5)

    # Required output aliases for downstream reporting.
    frame["predicted_groundwater"] = frame["predicted_groundwater_xgb"]

    # Data-driven confidence calibration: predict absolute error from validation fold.
    calib_X = train_frame.loc[X_test.index, ["nearest_piezometer_distance_km", "nearby_piezometer_count_10km", "lag_availability"]].copy()
    calib_y = np.abs(y_test_true - y_test_pred)
    calib_model = xgb.XGBRegressor(
        n_estimators=150,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        objective="reg:squarederror",
    )
    calib_model.fit(calib_X, calib_y)
    full_calib_X = frame[["nearest_piezometer_distance_km", "nearby_piezometer_count_10km", "lag_availability"]].copy()
    pred_abs_err = np.clip(calib_model.predict(full_calib_X), 0.0, None)
    frame["predicted_abs_error"] = pred_abs_err
    frame["confidence_score"] = 1.0 / (1.0 + frame["predicted_abs_error"])

    dist = pd.to_numeric(frame["nearest_piezometer_distance_km"], errors="coerce").fillna(25.0)
    count = pd.to_numeric(frame["nearby_piezometer_count_10km"], errors="coerce").fillna(0.0)
    frame["data_availability_component"] = np.clip(
        0.65 * frame["has_piezometer"].astype(float) + 0.35 * pd.to_numeric(frame["lag_availability"], errors="coerce").fillna(0.0),
        0.0,
        1.0,
    )
    frame["confidence_distance_component"] = np.exp(-np.clip(dist, 0.0, None) / 15.0)
    frame["confidence_density_component"] = np.clip(count / 5.0, 0.0, 1.0)
    uncertainty = pd.to_numeric(frame["nearby_groundwater_std_10km"], errors="coerce").fillna(0.0)
    frame["uncertainty_std_nearby"] = uncertainty
    frame["confidence_level"] = pd.cut(
        frame["confidence_score"],
        bins=[-1, 0.4, 0.7, 1.01],
        labels=["Low", "Medium", "High"],
    ).astype(str)

    fi = pd.DataFrame(
        {"feature": FEATURE_COLUMNS, "importance": model.feature_importances_}
    ).sort_values("importance", ascending=False).reset_index(drop=True)
    return ModelOutput(village_month_predictions=frame, metrics=metrics, feature_importance=fi)
