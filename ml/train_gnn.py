import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import torch.optim as optim
from sklearn.neighbors import KNeighborsRegressor

try:
    from ml.anomaly_detector import AdvancedAnomalyDetector
    from ml.graph_builder import SpatialGraphBuilder
    from ml.spatio_temporal_gnn import SpatioTemporalTransformerGNN
except ModuleNotFoundError:  # pragma: no cover
    from anomaly_detector import AdvancedAnomalyDetector
    from graph_builder import SpatialGraphBuilder
    from spatio_temporal_gnn import SpatioTemporalTransformerGNN

try:
    import xgboost as xgb
except Exception:  # pragma: no cover
    xgb = None


DEFAULT_FEATURES = [
    "rainfall_proxy",
    "rainfall_lag_1",
    "rainfall_lag_3",
    "recharge_index",
    "infiltration_score",
    "terrain_gradient",
    "aquifer_storage_factor",
    "extraction_stress",
    "proximity_surface_water_km",
]


def _ensure_point_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    out.geometry = out.geometry.centroid
    return out


def _prepare_dataset(input_path: Path) -> gpd.GeoDataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Missing input dataset: {input_path}")
    gdf = gpd.read_file(input_path)
    if "groundwater_level" not in gdf.columns:
        if "GW_Level" in gdf.columns:
            gdf["groundwater_level"] = pd.to_numeric(gdf["GW_Level"], errors="coerce")
        else:
            raise ValueError("Input must contain `groundwater_level` or `GW_Level`.")
    gdf["groundwater_level"] = pd.to_numeric(gdf["groundwater_level"], errors="coerce")
    gdf["has_sensor"] = gdf["groundwater_level"].notna().astype(int)

    # Rainfall lag features can be absent; derive stable fallbacks.
    if "rainfall_proxy" not in gdf.columns:
        gdf["rainfall_proxy"] = pd.to_numeric(gdf.get("flooded_vegetation_pct", 0.0), errors="coerce").fillna(0.0)
    gdf["rainfall_proxy"] = pd.to_numeric(gdf["rainfall_proxy"], errors="coerce").fillna(0.0)
    if "rainfall_lag_1" not in gdf.columns:
        gdf["rainfall_lag_1"] = gdf["rainfall_proxy"] * 0.9
    if "rainfall_lag_3" not in gdf.columns:
        gdf["rainfall_lag_3"] = gdf["rainfall_proxy"] * 0.75
    return gdf


def _prepare_features(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    features = pd.DataFrame(index=gdf.index)
    for col in DEFAULT_FEATURES:
        features[col] = pd.to_numeric(gdf.get(col, 0.0), errors="coerce").fillna(0.0)

    # Physical proxies used by graph edge weighting.
    features["elevation_dem"] = pd.to_numeric(
        gdf.get("Elevation", gdf.get("elevation_min", 0.0)),
        errors="coerce",
    ).fillna(0.0)
    features["lulc_code"] = pd.to_numeric(gdf.get("Built%", gdf.get("built_area_pct", 0.0)), errors="coerce").fillna(0.0)
    features["aquifer_code"] = pd.to_numeric(gdf.get("aquifer_storage_factor", 0.0), errors="coerce").fillna(0.0)
    features["geomorphology_code"] = pd.to_numeric(gdf.get("terrain_gradient", 0.0), errors="coerce").fillna(0.0)
    return features


def train_gnn_model(input_path: Path, output_path: Path, epochs: int = 200) -> dict:
    print("Starting hybrid GeoAI pipeline (GNN + features + anomaly + recharge)...")
    gdf = _prepare_dataset(input_path)
    if gdf["has_sensor"].sum() < 30:
        raise ValueError("Not enough labeled piezometer nodes for train/validation.")

    villages_gdf = _ensure_point_geometry(gdf[gdf["has_sensor"] == 0])
    piezometers_gdf = _ensure_point_geometry(gdf[gdf["has_sensor"] == 1])

    node_features_all = _prepare_features(gdf)
    node_features_ordered = pd.concat([node_features_all.loc[villages_gdf.index], node_features_all.loc[piezometers_gdf.index]])
    ordered_gdf = pd.concat([gdf.loc[villages_gdf.index], gdf.loc[piezometers_gdf.index]])

    builder = SpatialGraphBuilder(k_neighbors=8)
    data = builder.build_graph(villages_gdf, piezometers_gdf, node_features_ordered)
    if data.edge_attr is not None and data.edge_attr.dim() == 1:
        data.edge_attr = data.edge_attr.unsqueeze(1)

    y_values = pd.to_numeric(ordered_gdf["groundwater_level"], errors="coerce").fillna(0.0).values
    data.y = torch.tensor(y_values, dtype=torch.float).view(-1, 1)

    n_villages = len(villages_gdf)
    sensor_indices = np.arange(n_villages, n_villages + len(piezometers_gdf))
    np.random.shuffle(sensor_indices)
    split_idx = int(0.7 * len(sensor_indices))
    train_sensor_indices = sensor_indices[:split_idx]
    val_sensor_indices = sensor_indices[split_idx:]

    train_mask = torch.zeros(len(ordered_gdf), dtype=torch.bool)
    val_mask = torch.zeros(len(ordered_gdf), dtype=torch.bool)
    train_mask[train_sensor_indices] = True
    val_mask[val_sensor_indices] = True

    model = SpatioTemporalTransformerGNN(
        in_channels=node_features_ordered.shape[1],
        hidden_channels=32,
        out_channels=3,
        seq_len=1,
        edge_dim=1,
    )
    optimizer = optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-5)

    print(f"Training on {len(train_sensor_indices)} sensors, validating on {len(val_sensor_indices)}")
    model.train()
    for epoch in range(epochs + 1):
        optimizer.zero_grad()
        out = model(data.x, data.edge_index, data.edge_attr)
        loss_supervised = model.quantile_loss(out[train_mask], data.y[train_mask])
        loss_physics = model.physics_informed_loss(out, data.edge_index, data.edge_attr)
        total_loss = loss_supervised + loss_physics
        total_loss.backward()
        optimizer.step()
        if epoch % 50 == 0:
            with torch.no_grad():
                pred = out[:, 1].unsqueeze(1)
                val_mae = F.l1_loss(pred[val_mask], data.y[val_mask]).item()
                print(f"Epoch {epoch:3d} | train={loss_supervised.item():.4f} | val_mae={val_mae:.4f}")

    model.eval()
    with torch.no_grad():
        final_out = model(data.x, data.edge_index, data.edge_attr)
        gnn_preds = final_out[:, 1].cpu().numpy()
        p5 = final_out[:, 0].cpu().numpy()
        p95 = final_out[:, 2].cpu().numpy()
        val_targets = data.y[val_mask].squeeze().cpu().numpy()
        val_gnn = final_out[val_mask, 1].cpu().numpy()

    gnn_mae = float(np.mean(np.abs(val_gnn - val_targets)))
    coverage = float(np.mean((val_targets >= final_out[val_mask, 0].cpu().numpy()) & (val_targets <= final_out[val_mask, 2].cpu().numpy())))

    # Optional hybrid ensemble with XGBoost.
    ensemble_preds = gnn_preds.copy()
    xgb_mae = None
    if xgb is not None:
        xgb_model = xgb.XGBRegressor(n_estimators=150, learning_rate=0.05, max_depth=5, random_state=42)
        xgb_model.fit(data.x[train_mask].cpu().numpy(), data.y[train_mask].cpu().numpy().ravel())
        xgb_val = xgb_model.predict(data.x[val_mask].cpu().numpy())
        xgb_mae = float(np.mean(np.abs(xgb_val - val_targets)))
        full_xgb = xgb_model.predict(data.x.cpu().numpy())
        ensemble_preds = 0.7 * gnn_preds + 0.3 * full_xgb

    # Anomaly detection for abrupt and outlier behavior.
    anomaly_df = pd.DataFrame(
        {
            "predicted_depth": ensemble_preds,
            "uncertainty_range": (p95 - p5),
            "recharge_index": node_features_ordered["recharge_index"].values,
            "extraction_stress": node_features_ordered["extraction_stress"].values,
        }
    )
    detector = AdvancedAnomalyDetector(contamination=0.1)
    anomaly_df = detector.predict(anomaly_df, ["predicted_depth", "uncertainty_range", "recharge_index", "extraction_stress"])

    # Recharge recommendation rule (stress + recharge potential).
    ordered_gdf = ordered_gdf.copy()
    ordered_gdf["estimated_depth"] = ensemble_preds
    ordered_gdf["uncertainty_range"] = (p95 - p5)
    ordered_gdf["pred_q05"] = p5
    ordered_gdf["pred_q95"] = p95
    ordered_gdf["is_anomaly"] = anomaly_df["is_anomaly"].values.astype(bool)
    ordered_gdf["anomaly_score_ae"] = anomaly_df["anomaly_score_ae"].values
    ordered_gdf["recharge_recommended"] = (
        (node_features_ordered["recharge_index"] >= node_features_ordered["recharge_index"].quantile(0.65))
        & (ordered_gdf["estimated_depth"] >= np.nanpercentile(ordered_gdf["estimated_depth"], 65))
        & (node_features_ordered["infiltration_score"] >= node_features_ordered["infiltration_score"].quantile(0.5))
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ordered_gdf.to_file(output_path, driver="GeoJSON")

    metrics = {
        "rows": int(len(ordered_gdf)),
        "sensor_nodes": int(len(sensor_indices)),
        "gnn_val_mae": gnn_mae,
        "xgb_val_mae": xgb_mae,
        "ensemble_enabled": bool(xgb is not None),
        "calibration_coverage_90pct": coverage,
        "anomaly_rate": float(ordered_gdf["is_anomaly"].mean()),
        "recharge_candidates": int(ordered_gdf["recharge_recommended"].sum()),
        "output_geojson": str(output_path),
    }
    print("Training complete:", metrics)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hybrid GeoAI groundwater trainer")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/villages_with_features.geojson"),
        help="Input geojson with village features + labeled groundwater",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("ml/hybrid_geoai_predictions.geojson"),
        help="Output geojson path",
    )
    parser.add_argument("--epochs", type=int, default=200, help="Training epochs")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train_gnn_model(args.input, args.out, epochs=args.epochs)
