# High-Accuracy AI-Driven Groundwater Estimation System

This document outlines the architecture, training strategy, and deployment plan for the hybrid AI system designed to predict groundwater levels at the village level with <5% error across Andhra Pradesh, handling 1,800 piezometers and 18,000 villages.

## User Review Required

> [!IMPORTANT]
> This is a complete paradigm shift from the current XGBoost/Interpolation method to a state-of-the-art Deep Learning approach. 
> Please review the architecture, particularly the **PyTorch Geometric (GNN)** and **FastAPI integration** choices, before we begin implementation.

## Open Questions

> [!NOTE]
> 1. **Data Availability**: Do we have the historical time-series data for the 1,800 piezometers already stored in the PostgreSQL database, or do we need to implement a data ingestion pipeline first?
> 2. **Compute Resources**: Training a GNN + Transformer on 18,000 nodes requires significant compute (GPU recommended). Will this be trained locally on a GPU or deployed to a cloud environment (AWS EC2/GCP) for training?
> 3. **Frontend Integration**: Do you prefer to use 3D visualizers (like deck.gl) or standard Leaflet/Mapbox for the village-level groundwater maps and aquifer depth estimation?

## Proposed Architecture

We will implement a **Spatio-Temporal Graph Neural Network (ST-GNN)**. 

### 1. Data Preprocessing & Feature Engineering
- **Spatial**: Compute K-Nearest Neighbors (K=3-5) for piezometers to villages. Extract elevation gradient, DEM, distance to water bodies.
- **Temporal**: Create lag features (t-1, t-7, t-30). Encode seasonal cycles using sine/cosine transformations.
- **Hydrogeological**: Encode categorical data like soil type, aquifer maps, and LULC. Include rainfall (monthly/daily) and recharge rates.

### 2. Graph Construction
- **Nodes**: Piezometers (1,800) + Villages (18,000). Total: 19,800 nodes.
- **Edges**: Distance-based KNN connections.
- **Edge Weights**: Formulated based on physical distance, elevation difference, and hydrogeological similarity.

### 3. Model Design (Hybrid Deep Learning)
- **Input Features** -> 
- **Graph Attention Network (GAT / GraphSAGE)**: Captures spatial heterogeneity and diffuses piezometer readings to village nodes.
- **Transformer / LSTM Layer**: Captures temporal dynamics (e.g., delayed recharge from rainfall).
- **Dense / MLP Layers**: Regression output for groundwater level prediction.

### 4. Training Strategy
- **Dataset Splitting**: Spatial cross-validation (e.g., K-Fold over different districts/aquifers) to ensure generalization.
- **Loss Function**: `Total Loss = MSE(Predictions, Ground Truth) + λ * SpatialSmoothnessPenalty`.
- **Regularization**: Dropout layers and weight decay to prevent overfitting on sparse data.

### 5. Advanced Modules
- **Anomaly Detection**: Use an Isolation Forest or an Autoencoder on the piezometer time-series to flag abnormal sensor drops before feeding into the GNN.
- **Forecasting**: Extend the temporal component of the ST-GNN to predict horizons at 7, 30, and 90 days.
- **Uncertainty Estimation (Bonus)**: Implement Monte Carlo Dropout or a Gaussian Process layer to provide confidence intervals (e.g., ±0.5m) for every village prediction.
- **Ensemble (Bonus)**: Use the GNN embeddings as features for a secondary XGBoost model to boost final accuracy.

## Implementation Steps

### Phase 1: ML Pipeline (Backend/ML)
#### [NEW] `ml/spatio_temporal_gnn.py`
- PyTorch and PyTorch Geometric definitions for the GAT + Transformer model.
#### [NEW] `ml/graph_builder.py`
- Logic to construct the NetworkX/PyG graph from GeoDataFrames.
#### [NEW] `ml/anomaly_detector.py`
- Isolation Forest implementation for sensor validation.
#### [MODIFY] `ml/generate_dataset.py` & `ml/build_training_dataset.py`
- Update to support advanced feature engineering (lags, cyclic encoding).

### Phase 2: API & Deployment (FastAPI)
#### [MODIFY] `backend/app/main.py` & `backend/app/services.py`
- Expose endpoints:
  - `GET /api/predictions/village/{id}`
  - `GET /api/forecasts?horizon=30`
  - `GET /api/anomalies`
- Load the serialized ST-GNN PyTorch model using `torch.jit` or standard state_dict for fast inference.

### Phase 3: Frontend Integration (React + Leaflet/Mapbox)
#### [MODIFY] `frontend/src/components/MapView.jsx`
- Integrate new API endpoints.
- Add toggle for "Confidence Interval" layers (uncertainty visualization).
- Display 7/30/90 day forecasting charts on village click.

## Verification Plan

### Automated Tests
- Run unit tests for graph construction (verify edges only connect spatially adjacent/relevant nodes).
- Train model for 1 epoch on a dummy dataset to verify tensor shapes and backward pass.

### Manual Verification
- Evaluate the model on the spatial validation set. Verify that RMSE is strictly below 5% of the average groundwater depth.
- Start the FastAPI backend and test inference latency (must be < 500ms for village queries).
- Verify frontend map layers render properly with the new density/prediction data without overwhelming the DOM.
