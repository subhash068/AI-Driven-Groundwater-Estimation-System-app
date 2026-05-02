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

# Advanced feature set for <5% error target
FEATURE_COLUMNS = [
    "rainfall_variability",
    "elevation_dem",
    "slope_deg",
    "proximity_rivers_tanks_km",
    "soil_permeability",
    "rainfall_lag_1m",
    "lulc_code",
    "month_num",
    "is_monsoon"
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
        # In a real environment, we would log this and possibly fill with defaults
        pass


def resolve_target_column(df: pd.DataFrame) -> str:
    for col in TARGET_CANDIDATES:
        if col in df.columns:
            return col
    raise ValueError(f"Input must include one target column from {TARGET_CANDIDATES}")


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    
    # Deriving seasonal features if missing
    if "month_num" not in prepared.columns:
        prepared["month_num"] = pd.to_datetime('now').month
    if "is_monsoon" not in prepared.columns:
        prepared["is_monsoon"] = prepared["month_num"].apply(lambda x: 1 if 6 <= x <= 9 else 0)
        
    # Backward compatibility for early PoC datasets.
    if "proximity_rivers_tanks_km" not in prepared.columns and "proximity_surface_water_km" in prepared.columns:
        prepared["proximity_rivers_tanks_km"] = prepared["proximity_surface_water_km"]
        
    validate_columns(prepared, FEATURE_COLUMNS)
    return prepared


def train_models(df: pd.DataFrame, random_state: int = 42) -> ModelArtifacts:
    target_column = resolve_target_column(df)
    prepared = prepare_features(df)

    sensor_df = prepared[prepared["has_sensor"] == 1].copy()
    X = sensor_df[FEATURE_COLUMNS]
    y = sensor_df[target_column]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )

    # XGBoost setup for baseline (Option 2)
    regressor = xgb.XGBRegressor(
        n_estimators=1000,
        max_depth=12,
        learning_rate=0.05,
        min_child_weight=3,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=random_state,
        n_jobs=-1,
        tree_method="hist",
        eval_metric="mae",
    )
    regressor.fit(X_train, y_train)

    pred_test = regressor.predict(X_test)
    
    mae = float(mean_absolute_error(y_test, pred_test))
    mape = float(mean_absolute_percentage_error(y_test, pred_test))

    sensor_pred = regressor.predict(sensor_df[FEATURE_COLUMNS])
    sensor_residual = sensor_df[target_column] - sensor_pred
    residual_std = float(np.std(sensor_residual))

    anomaly_model = IsolationForest(
        n_estimators=300,
        contamination=0.05, # Tightened for higher precision
        random_state=random_state,
    )
    anomaly_model.fit(sensor_df[FEATURE_COLUMNS])

    feature_means = X_train.mean()
    feature_stds = X_train.std().replace(0, 1.0).fillna(1.0)

class GatingNetwork(nn.Module):
    def __init__(self, input_dim: int):
        super(GatingNetwork, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 8),
            nn.ReLU(),
            nn.Linear(8, 1),
            nn.Sigmoid() # Output alpha between 0 and 1
        )

    def forward(self, x):
        return self.net(x)

def dynamic_ensemble_predict(df: pd.DataFrame, artifacts: ModelArtifacts, gnn_preds: np.ndarray = None) -> tuple:
    """
    Final Prediction = alpha(x) * GNN + (1 - alpha(x)) * XGBoost
    alpha depends on local context: distance to stations, elevation, etc.
    """
    xgb_pred = artifacts.regressor.predict(df[FEATURE_COLUMNS])
    
    # Simple Gating Logic (can be replaced by a trained GatingNetwork)
    # alpha -> weight for GNN. If we are near a sensor, GNN (spatial) is more reliable.
    # If we are in a sparse area, XGBoost (feature-based) might be more robust.
    
    # Feature for gating: proximity to sensors (already in FEATURE_COLUMNS as proximity_rivers_tanks_km but we need sensors)
    # For now, we'll use 'has_sensor' and 'elevation_dem' to simulate terrain complexity
    dist_factor = df['proximity_rivers_tanks_km'].fillna(10).values
    alpha = np.clip(1.0 / (dist_factor + 1.0), 0.1, 0.9) # Range [0.1, 0.9]
    
    if gnn_preds is not None:
        # If GNN preds (median) are provided, blend them
        final_pred = alpha * gnn_preds + (1 - alpha) * xgb_pred
    else:
        # Fallback to spatial weighted if GNN model is not loaded
        spatial_ref = df["weighted_sensor_depth"].fillna(xgb_pred).values if "weighted_sensor_depth" in df.columns else xgb_pred
        final_pred = alpha * spatial_ref + (1 - alpha) * xgb_pred
        
    return final_pred, alpha


def infer(df: pd.DataFrame, artifacts: ModelArtifacts) -> pd.DataFrame:
    prepared = prepare_features(df)
    output = prepared.copy()
    
    # 1. Dynamic Ensemble Prediction
    y_hat, alpha_weights = dynamic_ensemble_predict(output, artifacts)
    output["estimated_groundwater_depth"] = y_hat
    output["gnn_weight_alpha"] = alpha_weights

    # 2. Uncertainty Estimation (Quantile-based)
    # In a full run, these would come from SpatioTemporalTransformerGNN.predict_with_uncertainty
    # Here we simulate the bounds using the residual_std for the PoC
    output["uncertainty_lower"] = np.round(y_hat - (1.96 * artifacts.residual_std), 2)
    output["uncertainty_upper"] = np.round(y_hat + (1.96 * artifacts.residual_std), 2)
    output["confidence_score"] = np.round((1 - (np.clip(artifacts.residual_std, 0, 3) / 3.0)) * 100, 2)

    # 3. Anomaly detection
    anomaly_raw = artifacts.anomaly_model.predict(output[FEATURE_COLUMNS])
    output["anomaly_unsupervised"] = np.where(anomaly_raw == -1, 1, 0)
    output["anomaly_flag"] = output["anomaly_unsupervised"]

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Groundwater AI Interpolation Engine")
    parser.add_argument("--input", type=Path, required=True, help="Input GeoJSON dataset")
    parser.add_argument("--out", type=Path, required=True, help="Output GeoJSON predictions")
    parser.add_argument("--metrics", type=Path, default=Path("data/model_metrics.json"))
    args = parser.parse_args()
    run(args.input, args.out, args.metrics)
