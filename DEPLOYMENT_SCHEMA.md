# Scientific-Grade Groundwater AI Deployment Schema

This document outlines the production infrastructure for the hardened Spatio-Temporal Groundwater Intelligence System.

## 1. Kubernetes Infrastructure (K8s)
The system is designed for high-availability deployment on a managed Kubernetes cluster (e.g., AKS, EKS, or GKE).

### Cluster Specifications
- **Node Pools**:
  - `cpu-pool`: 3x `Standard_D4s_v3` for API and Frontend.
  - `gpu-pool`: 1x `Standard_NC6s_v3` (NVIDIA Tesla P100) for GNN retraining and real-time simulation.
- **Namespaces**: `groundwater-prod`, `groundwater-staging`.

### Deployment Components
- `backend-api`: FastAPI service (3 replicas, HPA based on CPU/Request).
- `frontend-ui`: React/Vite dashboard (served via Nginx).
- `ml-inference-worker`: Sidecar container or dedicated pod for heavy GNN simulations.
- `postgres-gis`: Managed database (e.g., Azure Database for PostgreSQL with PostGIS).

## 2. Data Version Control (DVC)
To manage the 18,000 village datasets and ensure reproducibility of the scientific models.

### DVC Workflow
- **Remote Storage**: S3 or Azure Blob Storage.
- **Pipeline Stages**:
  ```bash
  dvc run -n preprocess \
          -d data/raw/villages.geojson \
          -o data/processed/features.csv \
          python scripts/preprocess.py
          
  dvc run -n train_gnn \
          -d data/processed/features.csv \
          -o ml/stgnn_model.pt \
          python ml_pipeline/training/train_gnn.py --epochs 200
  ```
- **Tracking**: Use `dvc.yaml` to track data hashes alongside Git commits.

## 3. MLflow Model Registry & Tracking
Ensures every model version is benchmarked against the <5% error metric.

### Experiment Tracking
- **Parameters**: `hidden_channels`, `num_heads`, `alpha`, `beta` (PINN weights).
- **Metrics**: `MAE`, `RMSE`, `Divergence_Residual`, `Calibration_Coverage`.
- **Artifacts**: Model state dicts, SHAP importance plots.

### Registry Lifecycle
- **Candidate**: MAE < 0.5m and Divergence < 0.1.
- **Production**: Best model selected for API serving.

## 4. CI/CD Pipeline
- **Validation**: GitHub Actions runs `pytest` and checks if `MLflow` metrics meet the threshold.
- **Containerization**: Docker images pushed to private Registry (ACR/ECR).
- **GitOps**: `ArgoCD` syncs the cluster state with the `infra/k8s` manifest directory.

---
*Lead Hydro-AI Engineer Approval Required for Model Promotion.*
