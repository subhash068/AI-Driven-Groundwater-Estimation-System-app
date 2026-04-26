import argparse
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, precision_score
from sklearn.model_selection import train_test_split


FEATURE_COLUMNS = [
    "rainfall_variability",
    "elevation_dem",
    "slope_deg",
    "proximity_rivers_tanks_km",
    "soil_permeability",
    "rainfall_lag_1m",
    "lulc_code",
]

TARGET_CANDIDATES = ["depth_to_water_level", "groundwater_depth", "dtw"]
DATE_CANDIDATES = ["date", "observed_date", "timestamp"]


@dataclass
class ModelArtifacts:
    regressor: "xgb.XGBRegressor"
    anomaly_model: IsolationForest
    residual_std: float
    feature_means: pd.Series
    feature_stds: pd.Series
    metrics: dict


def validate_columns(df: pd.DataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def resolve_target_column(df: pd.DataFrame) -> str:
    for col in TARGET_CANDIDATES:
        if col in df.columns:
            return col
    raise ValueError(f"Input must include one target column from {TARGET_CANDIDATES}")


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    # Backward compatibility for early PoC datasets.
    if "proximity_rivers_tanks_km" not in prepared.columns and "proximity_surface_water_km" in prepared.columns:
        prepared["proximity_rivers_tanks_km"] = prepared["proximity_surface_water_km"]
    validate_columns(prepared, FEATURE_COLUMNS)
    return prepared


def infer_month(df: pd.DataFrame) -> pd.Series:
    if "month_num" in df.columns:
        return df["month_num"].astype(int)
    for col in DATE_CANDIDATES:
        if col in df.columns:
            return pd.to_datetime(df[col]).dt.month.astype(int)
    return pd.Series(np.ones(len(df), dtype=int), index=df.index)


def seasonal_norms(df: pd.DataFrame, target_column: str) -> pd.DataFrame:
    month_num = infer_month(df)
    temp = df.copy()
    temp["month_num"] = month_num
    norms = (
        temp.groupby(["village_id", "month_num"], dropna=False)[target_column]
        .median()
        .rename("seasonal_norm_depth")
        .reset_index()
    )
    return norms


def train_models(df: pd.DataFrame, random_state: int = 42) -> ModelArtifacts:
    target_column = resolve_target_column(df)
    prepared = prepare_features(df)
    validate_columns(prepared, [target_column, "has_sensor", "is_anomaly_label"])

    sensor_df = prepared[prepared["has_sensor"] == 1].copy()
    X = sensor_df[FEATURE_COLUMNS]
    y = sensor_df[target_column]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )

    regressor = xgb.XGBRegressor(
        n_estimators=500,
        max_depth=20,
        min_child_weight=5,
        random_state=random_state,
        n_jobs=-1,
        tree_method="hist",
        eval_metric="mae",
    )
    regressor.fit(X_train, y_train)

    pred_test = regressor.predict(X_test)
    residuals = y_test - pred_test

    mae = float(mean_absolute_error(y_test, pred_test))
    mape = float(mean_absolute_percentage_error(y_test, pred_test))

    sensor_pred = regressor.predict(sensor_df[FEATURE_COLUMNS])
    sensor_residual = sensor_df[target_column] - sensor_pred
    residual_std = float(np.std(sensor_residual))

    anomaly_model = IsolationForest(
        n_estimators=300,
        contamination=0.1,
        random_state=random_state,
    )
    anomaly_model.fit(sensor_df[FEATURE_COLUMNS])

    feature_means = X_train.mean()
    # Avoid divide-by-zero during inference if a feature is constant in training data.
    feature_stds = X_train.std().replace(0, 1.0).fillna(1.0)

    anomaly_raw = anomaly_model.predict(sensor_df[FEATURE_COLUMNS])
    anomaly_pred = np.where(anomaly_raw == -1, 1, 0)
    anomaly_precision = float(
        precision_score(sensor_df["is_anomaly_label"], anomaly_pred, zero_division=0)
    )

    sensor_eval = sensor_df.copy()
    sensor_eval["month_num"] = infer_month(sensor_eval)
    norms = seasonal_norms(sensor_eval, target_column)
    sensor_eval = sensor_eval.merge(norms, on=["village_id", "month_num"], how="left")
    drop_ratio = (
        (sensor_eval["seasonal_norm_depth"] - sensor_eval[target_column])
        / (np.abs(sensor_eval["seasonal_norm_depth"]) + 1e-9)
    )
    seasonal_rule_pred = (drop_ratio > 0.05).astype(int)
    seasonal_rule_precision = float(
        precision_score(sensor_df["is_anomaly_label"], seasonal_rule_pred, zero_division=0)
    )

    metrics = {
        "mae": mae,
        "mape": mape,
        "anomaly_precision_isolation_forest": anomaly_precision,
        "anomaly_precision_seasonal_drop_rule": seasonal_rule_precision,
        "target_error_within_5pct": mape <= 0.05,
        "target_anomaly_precision_90pct": seasonal_rule_precision >= 0.90,
    }
    return ModelArtifacts(
        regressor=regressor,
        anomaly_model=anomaly_model,
        residual_std=residual_std,
        feature_means=feature_means,
        feature_stds=feature_stds,
        metrics=metrics,
    )


def infer(df: pd.DataFrame, artifacts: ModelArtifacts) -> pd.DataFrame:
    prepared = prepare_features(df)
    validate_columns(prepared, ["village_id"])

    target_column = next((c for c in TARGET_CANDIDATES if c in prepared.columns), None)
    output = prepared.copy()
    y_hat = artifacts.regressor.predict(output[FEATURE_COLUMNS])
    output["estimated_groundwater_depth"] = y_hat

    # XGBoost does not expose sklearn-style `estimators_`, so confidence is derived
    # from how far inference rows are from the training feature distribution.
    z_scores = (
        output[FEATURE_COLUMNS].sub(artifacts.feature_means, axis=1)
        .abs()
        .div(artifacts.feature_stds, axis=1)
    )
    mean_feature_distance = z_scores.mean(axis=1).to_numpy()
    residual_penalty = np.clip(artifacts.residual_std, 0, 3)
    normalized_uncertainty = np.clip(mean_feature_distance + residual_penalty, 0, 6)
    output["confidence_score"] = np.round((1 - (normalized_uncertainty / 6.0)) * 100, 2)

    anomaly_raw = artifacts.anomaly_model.predict(output[FEATURE_COLUMNS])
    output["anomaly_unsupervised"] = np.where(anomaly_raw == -1, 1, 0)

    output["month_num"] = infer_month(output)
    if target_column is not None:
        norms = seasonal_norms(output, target_column)
    elif "seasonal_norm_depth" in output.columns:
        norms = output[["village_id", "month_num", "seasonal_norm_depth"]]
    else:
        norms = pd.DataFrame(columns=["village_id", "month_num", "seasonal_norm_depth"])

    if not norms.empty:
        output = output.merge(norms, on=["village_id", "month_num"], how="left")
        drop_ratio = (
            (output["seasonal_norm_depth"] - output["estimated_groundwater_depth"])
            / (np.abs(output["seasonal_norm_depth"]) + 1e-9)
        )
        output["depletion_vs_seasonal_norm"] = np.round(drop_ratio * 100, 2)
        output["depletion_gt_5pct"] = (drop_ratio > 0.05).astype(int)
    else:
        output["seasonal_norm_depth"] = np.nan
        output["depletion_vs_seasonal_norm"] = np.nan
        output["depletion_gt_5pct"] = output["anomaly_unsupervised"]

    # Required anomaly behavior: drop >5% versus seasonal norm.
    output["anomaly_flag"] = output["depletion_gt_5pct"].astype(int)

    return output


def run(input_path: Path, output_path: Path, metrics_path: Path) -> None:
    gdf = gpd.read_file(input_path)
    artifacts = train_models(gdf)
    output = infer(gdf, artifacts)

    output_gdf = gpd.GeoDataFrame(output, geometry=gdf.geometry, crs=gdf.crs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_gdf.to_file(output_path, driver="GeoJSON")

    pd.Series(artifacts.metrics).to_json(metrics_path, indent=2)
    print("Model metrics:", artifacts.metrics)
    print(f"Saved estimates to: {output_path}")
    print(f"Saved metrics to: {metrics_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Groundwater interpolation engine")
    parser.add_argument("--input", type=Path, required=True, help="Input GeoJSON dataset")
    parser.add_argument("--out", type=Path, required=True, help="Output GeoJSON predictions")
    parser.add_argument(
        "--metrics",
        type=Path,
        default=Path("data/model_metrics.json"),
        help="Output JSON for evaluation metrics",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.input, args.out, args.metrics)
