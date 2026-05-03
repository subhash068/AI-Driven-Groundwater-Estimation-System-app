import os
import sys
import argparse
import json
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import pandas as pd
import geopandas as gpd
from torch_geometric.data import Data
from sklearn.preprocessing import StandardScaler

from ml_pipeline.models.deep_learning.spatio_temporal_gnn import SpatioTemporalTransformerGNN
from ml_pipeline.graph.graph_builder import SpatialGraphBuilder
from ml_pipeline.models.physics.constraints import (
    groundwater_balance_constraint,
    hydraulic_gradient_constraint,
    aquifer_continuity_constraint
)
from ml_pipeline.evaluation.anomaly_detector import AdvancedAnomalyDetector

class ScientificSTGNNTrainer:
    """
    Expert-level Spatio-Temporal GNN Trainer.
    Implements multi-head attention over time and spatial message passing.
    Bridges 1:10 sparsity by propagating sensor signals to all 18,000 villages.
    """
    
    def __init__(self, data_path: Path, output_dir: Path):
        self.data_path = data_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Primary features for the ST-GNN
        self.feature_cols = [
            "rainfall_proxy", "recharge_index", "extraction_stress", 
            "terrain_gradient", "aquifer_storage_factor", "elevation_dem",
            "distance_to_canal_km", "distance_to_tank_km", "built_area_pct"
        ]

    def load_and_sync_data(self):
        print("[1/5] Loading and synchronizing geospatial data...")
        gdf = gpd.read_file(self.data_path)
        
        if "groundwater_level" not in gdf.columns:
            gdf["groundwater_level"] = pd.to_numeric(gdf.get("GW_Level", np.nan), errors="coerce")
        
        gdf["has_sensor"] = gdf["groundwater_level"].notna().astype(int)
        villages = gdf[gdf["has_sensor"] == 0].copy()
        piezometers = gdf[gdf["has_sensor"] == 1].copy()
        
        return villages, piezometers, gdf

    def build_temporal_tensor(self, gdf):
        """
        Builds a 3D tensor (nodes, seq_len, features) for the ST-GNN.
        Simulates temporal sequence using rainfall lags to teach the model seasonal dynamics.
        """
        n_nodes = len(gdf)
        seq_len = 3
        n_features = len(self.feature_cols)
        
        # Initialize tensor
        x_tensor = torch.zeros((n_nodes, seq_len, n_features))
        
        # We'll use: 
        # t-2: features with rainfall_lag_3
        # t-1: features with rainfall_lag_1
        # t-0: current features
        
        scaler = StandardScaler()
        base_features = gdf[self.feature_cols].copy()
        for col in self.feature_cols:
            base_features[col] = pd.to_numeric(base_features[col], errors="coerce").fillna(0.0)
            
        scaled_base = scaler.fit_transform(base_features)
        
        # Fill sequence steps
        for t in range(seq_len):
            xt = scaled_base.copy()
            if t == 0: # t-2
                xt[:, 0] = pd.to_numeric(gdf.get("rainfall_lag_3", 0), errors="coerce").fillna(0.0)
            elif t == 1: # t-1
                xt[:, 0] = pd.to_numeric(gdf.get("rainfall_lag_1", 0), errors="coerce").fillna(0.0)
            # t-2 (t=0) is already current rainfall in feature_cols[0]
            
            x_tensor[:, t, :] = torch.tensor(xt, dtype=torch.float)
            
        return x_tensor, base_features

    def train(self, epochs=250):
        villages, piezometers, full_gdf = self.load_and_sync_data()
        ordered_gdf = pd.concat([villages, piezometers]).reset_index(drop=True)
        
        x_tensor, features_df = self.build_temporal_tensor(ordered_gdf)
        x_tensor = x_tensor.to(self.device)
        
        # Graph Construction
        builder = SpatialGraphBuilder(k_neighbors=8)
        data = builder.build_graph(villages, piezometers, features_df)
        data = data.to(self.device)
        
        y = torch.tensor(ordered_gdf["groundwater_level"].fillna(0).values, dtype=torch.float).view(-1, 1).to(self.device)
        
        n_villages = len(villages)
        n_sensors = len(piezometers)
        sensor_indices = np.arange(n_villages, n_villages + n_sensors)
        np.random.shuffle(sensor_indices)
        split = int(0.8 * n_sensors)
        train_idx, val_idx = sensor_indices[:split], sensor_indices[split:]
        
        model = SpatioTemporalTransformerGNN(
            in_channels=len(self.feature_cols),
            hidden_channels=48,
            out_channels=3,
            seq_len=3,
            num_heads=4,
            edge_dim=1 if data.edge_attr is not None else None
        ).to(self.device)
        
        optimizer = optim.Adam(model.parameters(), lr=0.003, weight_decay=1e-4)
        
        physics_inputs = torch.tensor(
            features_df[["recharge_index", "extraction_stress", "terrain_gradient"]].values if "recharge_index" in features_df.columns else np.zeros((len(ordered_gdf), 3)),
            dtype=torch.float
        ).to(self.device)
        
        aquifer_idx = torch.tensor(pd.to_numeric(ordered_gdf.get("aquifer_type_enc", 0), errors="coerce").fillna(0).values, dtype=torch.long).to(self.device)
        
        print(f"[2/5] Training ST-GNN with Physics-Informed Layers...")
        best_val_mae = float('inf')
        
        for epoch in range(1, epochs + 1):
            model.train()
            optimizer.zero_grad()
            
            # Forward pass with (nodes, seq, features)
            out = model(x_tensor, data.edge_index, edge_attr=data.edge_attr, aquifer_idx=aquifer_idx, physics_inputs=physics_inputs)
            
            # Loss Components
            loss_sup = model.quantile_loss(out[train_idx], y[train_idx])
            
            pred_median = out[:, 1]
            loss_balance = groundwater_balance_constraint(pred_median, x_tensor[:, -1, 0], x_tensor[:, -1, 2])
            
            elevation = torch.tensor(pd.to_numeric(ordered_gdf.get("elevation_dem", 0), errors="coerce").fillna(0).values, dtype=torch.float).to(self.device)
            loss_grad = hydraulic_gradient_constraint(pred_median, elevation, data.edge_index)
            loss_cont = aquifer_continuity_constraint(pred_median, data.edge_index, data.edge_attr.squeeze() if data.edge_attr is not None else torch.ones(data.edge_index.size(1)).to(self.device))
            
            total_loss = 1.0 * loss_sup + 0.2 * loss_balance + 0.1 * loss_grad + 0.05 * loss_cont
            
            total_loss.backward()
            optimizer.step()
            
            if epoch % 50 == 0:
                model.eval()
                with torch.no_grad():
                    v_out = model(x_tensor, data.edge_index, edge_attr=data.edge_attr, aquifer_idx=aquifer_idx, physics_inputs=physics_inputs)
                    v_mae = F.l1_loss(v_out[val_idx, 1], y[val_idx].squeeze()).item()
                    print(f"Epoch {epoch:3d} | Loss: {total_loss.item():.4f} | Val MAE: {v_mae:.4f}")
                    if v_mae < best_val_mae:
                        best_val_mae = v_mae
                        torch.save(model.state_dict(), self.output_dir / "scientific_stgnn.pt")

        return model, x_tensor, data, ordered_gdf, physics_inputs, aquifer_idx

    def finalize(self, model, x_tensor, data, gdf, physics_inputs, aquifer_idx):
        print("[4/5] Running Global Inference...")
        model.eval()
        with torch.no_grad():
            final_out = model(x_tensor, data.edge_index, edge_attr=data.edge_attr, aquifer_idx=aquifer_idx, physics_inputs=physics_inputs)
            
        preds = final_out.cpu().numpy()
        gdf["predicted_depth"] = preds[:, 1]
        gdf["pred_q05"] = preds[:, 0]
        gdf["pred_q95"] = preds[:, 2]
        gdf["confidence"] = 1.0 - (preds[:, 2] - preds[:, 0]) / (preds[:, 1] + 1e-6)
        
        print("[5/5] Mapping Anomaly & Recharge Zones...")
        # Anomaly Detection based on prediction residuals and uncertainty
        gdf["is_anomaly"] = (gdf["pred_q95"] - gdf["pred_q05"]) > (gdf["pred_q95"] - gdf["pred_q05"]).mean() + 2 * (gdf["pred_q95"] - gdf["pred_q05"]).std()
        
        # Recharge Priority
        gdf["recharge_priority"] = (
            (gdf["predicted_depth"] > gdf["predicted_depth"].mean()) & 
            (gdf["infiltration_score"] > 0.5)
        ).astype(int)
        
        out_path = self.output_dir / "scientific_stgnn_output.geojson"
        gdf.to_file(out_path, driver="GeoJSON")
        print(f"Complete! Results saved to {out_path}")

if __name__ == "__main__":
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument("--input", default="data/processed/villages_with_features.geojson")
    args_parser.add_argument("--output", default="output/scientific_stgnn")
    args = args_parser.parse_args()
    
    trainer = ScientificSTGNNTrainer(Path(args.input), Path(args.output))
    m, x, d, g, p, a = trainer.train(epochs=200)
    trainer.finalize(m, x, d, g, p, a)
