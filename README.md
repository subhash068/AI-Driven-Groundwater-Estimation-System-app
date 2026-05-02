# AI-Driven Groundwater Estimation System

Government-grade starter platform for village-level groundwater estimation, forecasting, anomaly detection, recharge planning, and dashboard visualization.

## What Is Implemented

### 1) Data Engineering & Storage
- PostgreSQL + PostGIS spatial schema for:
  - `villages` (polygons)
  - `piezometers` (points)
  - `hydrogeology`
  - `rainfall_history`
- Spatial indexing (`GIST`) for fast proximity/spatial joins.
- Spatial nearest-neighbor function:
  - `groundwater.find_nearest_piezometers(village_id, limit)` with weighted-distance fields.
- Feature store for ML:
  - `groundwater.village_features`
  - `groundwater.ml_training_view`
- Raster support:
  - `postgis_raster` extension
  - `groundwater.raster_products`
- Ingestion audit tracking:
  - `groundwater.ingestion_runs`

### 2) ML & AI
- Interpolation engine:
  - XGBoost regression with hydrogeological covariates.
  - Confidence scoring from feature-distance and residual spread.
- Training features supported:
  - `elevation_dem`
  - `slope_deg`
  - `proximity_rivers_tanks_km`
  - `proximity_surface_water_km` from RTGS canals, streams, drainage, and MI tanks
  - `soil_permeability`
  - `rainfall_variability`
  - `rainfall_lag_1m`
  - `lulc_code`
- Target aliases supported:
  - `depth_to_water_level`, `groundwater_depth`, `dtw`
- Anomaly detection:
  - Isolation Forest (unsupervised score path)
  - Seasonal anomaly rule implemented: drop `>5%` vs seasonal norm.
  - Precision metrics emitted in model metrics JSON.
- Forecasting:
  - Prophet-based module (`ml/forecasting_module.py`)
  - LSTM-style 3-month module (`ml/lstm_forecast.py`) with fallback behavior.
- Spatial-join dataset builder:
  - `ml/build_training_dataset.py`

### 3) Backend API (FastAPI + Redis + RBAC)
- Async FastAPI service with Redis caching.
- OAuth2/JWT auth + role-based access control (`viewer`, `engineer`, `admin`).
- OpenID discovery stub endpoint included.
- GIS-ready output modes (JSON/GeoJSON) for planning and alerts.
- PDF export endpoint for field reporting.

### 4) Geospatial Serving
- GeoServer bootstrap script to publish WMS/WFS-ready PostGIS layers.
- MapServer mapfile alternative.

### 5) Frontend Dashboard
- React + Leaflet/react-leaflet + Three.js.
- 2D village polygon rendering with status color classes.
- 3D terrain toggle + aquifer stratification visualization (Leaflet overlays + Three.js scene).
- Temporal playback slider: 24 months.
- District/Mandal/Village filtering.
- Auto-zoom to selected village and popup with forecast details.
- OpenStreetMap-backed map rendering with local GeoJSON fallbacks.

### 6) Farmer Portal (Mobile-First)
- Lightweight low-bandwidth page under `frontend/public/farmer`.
- GPS auto-locate to nearest village (`/village/locate`).
- Visual icon advisories (safe/warning/critical).
- Crop recommendation text by water status.
- i18next multi-language support:
  - English (`en`)
  - Telugu (`te`)

---

## Repository Layout

- `database/phase1_postgis.sql`: core PostGIS schema + spatial function + indexes
- `database/phase2_feature_store.sql`: ML feature store + training view
- `database/phase3_api_support.sql`: forecast/anomaly/estimate tables + seasonal norms
- `database/phase4_security_ingestion.sql`: auth tables + raster + ingestion metadata
- `database/phase5_bootstrap.sql`: deterministic bootstrap lineage columns + logs + dashboard materialized view
- `ml/interpolation_engine.py`: estimation + confidence + anomaly logic + metrics
- `ml/build_training_dataset.py`: spatial-join training dataset generation
- `ml/forecasting_module.py`: Prophet forecasting pipeline
- `ml/lstm_forecast.py`: LSTM-style forecast generator
- `model/pipeline.py`: groundwater feature engineering + XGBoost + Kriging export pipeline
- `model/stage_data.py`: stages Krishna source files into `data/raw`
- `backend/app/main.py`: API routes
- `backend/app/auth.py`: OAuth2/JWT auth + RBAC guards
- `backend/app/services.py`: DB query/service layer
- `backend/scripts/seed_user.py`: bootstrap API users
- `airflow/dags/groundwater_ingestion_dag.py`: ingestion DAG (rainfall/piezometer/LULC)
- `geoserver/bootstrap_geoserver.py`: GeoServer workspace/store/layer bootstrap
- `mapserver/groundwater.map`: MapServer WMS/WFS alternative
- `frontend/src/App.jsx`: main dashboard UI
- `frontend/src/AquiferScene.jsx`: Three.js aquifer visualization
- `frontend/public/farmer/`: mobile-first farmer portal
- `infra/docker-compose.yml`: PostGIS + Redis + GeoServer local stack

### Raw Data Bundles

The project now consumes the following source archives from `data/raw/`:

- `Village_Mandal_DEM_Soils_MITanks_Krishna.zip`: village boundaries, soils, and MI tank polygons
- `Aquifers_Krishna.zip`: aquifer polygons
- `GM_Krishna.zip`: geomorphology polygons
- `GTWells_Krishna.zip`: bore-well inventory and derived well stats
- `KrishnaLULC.zip`: 2011 and 2021 land-use / land-cover rasters
- `K_DEM1.zip`: DEM raster and world file
- `K_Canals.zip`, `K_Strms.zip`, `K_Drain.zip`, `K_Tanks.zip`: surface-water layers used for proximity features
- `Pumping Data.xlsx` and `PzWaterLevel_2024.xlsx`: pumping and piezometer observations

These bundles feed three main entry points:

- `scripts/build_authoritative_krishna_data.py` builds the frontend-ready GeoJSON and summary files
- `ml_pipeline/data/generate_dataset.py` and `ml_pipeline/training/run_pipeline.py` build model features and predictions
- `model/pipeline.py` and `model/stage_data.py` keep the legacy CSV/GeoJSON workflow in sync

---

## Quick Start

### Groundwater AI Pipeline
```bash
# 1) Stage Krishna source files into repo-local data/raw (optional if already present)
python -m model.stage_data

# 2) Build village-level features + XGBoost + Kriging outputs
python -m model.pipeline --kriging-strategy residual
python -m model.pipeline --export

# 3) Run backend API
uvicorn backend.app.main:app --reload --reload-dir backend/app --reload-exclude patch.py

# 4) Run frontend dashboard
cd frontend
npm install
npm run dev
# open http://localhost:5173/dashboard
```

### 1) Start Infrastructure (optional but recommended)
```bash
cd infra
docker compose up -d
```

### 2) Initialize Database
Run SQL in this order:
```sql
\i database/phase1_postgis.sql
\i database/phase2_feature_store.sql
\i database/phase3_api_support.sql
\i database/phase4_security_ingestion.sql
\i database/phase5_bootstrap.sql
```

### 3) Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 4) Seed an API User
```bash
python -m backend.scripts.seed_user --username admin --full-name "System Admin" --password "ChangeMe123!" --role admin
```

### 5) Run Backend API
```bash
uvicorn backend.app.main:app --reload --reload-dir backend/app --reload-exclude patch.py
```

### 6) Build Training Dataset
```bash
python ml/build_training_dataset.py --out data/training_dataset.csv
```

### 7) Run Interpolation
```bash
python ml/interpolation_engine.py --input data/training_dataset.geojson --out data/village_estimates.geojson --metrics data/model_metrics.json
```

### 8) Run Forecasting
```bash
python ml/forecasting_module.py --input data/timeseries.csv --out data/forecast_output.csv
python ml/lstm_forecast.py --input data/timeseries.csv --out data/lstm_forecast_output.csv --horizon 3
python -m model.train_from_csv --predict-ntr
```

### 9) Run Dashboard
```bash
cd frontend
npm install
npm run dev
```

### 10) Run Farmer Portal
Open:
- `http://localhost:5173/farmer/`

---

## API Endpoints

### Authentication
- `POST /auth/token`
- `GET /auth/me`
- `GET /.well-known/openid-configuration`

### Groundwater Core
- `GET /get-village-status/{village_id}`
- `GET /village/{village_id}/forecast`
- `GET /alerts/anomalies?output_format=json|geojson`
- `GET /planning/recharge-zones?output_format=json|geojson`
- `GET /recharge-recommendations`
- `GET /village/locate?lat=..&lon=..`

### Advisories / Admin
- `GET /farmer-advisories`
- `POST /farmer-advisories` (`engineer`/`admin`)
- `POST /admin/village-estimates` (`engineer`/`admin`)

### Reporting
- `GET /export/village-report/{village_id}`

---

## Airflow Ingestion

DAG file:
- `airflow/dags/groundwater_ingestion_dag.py`

Expected environment variables:
- `DB_DSN_SYNC`
- `IMD_RAINFALL_API`
- `TRMM_RAINFALL_API`
- `PIEZOMETER_API`
- `SENTINEL_LULC_API`

Pipelines included:
- Real-time/daily rainfall ingestion
- Daily piezometer readings ingestion
- Sentinel-2 LULC raster ingestion
- Run status tracking in `groundwater.ingestion_runs`

---

## GeoServer / MapServer

### GeoServer bootstrap
```bash
python geoserver/bootstrap_geoserver.py
```

Publishes layers such as:
- `groundwater:villages`
- `groundwater:hydrogeology`
- `groundwater:village_features`
- `groundwater:rainfall_history`

### MapServer alternative
- Use `mapserver/groundwater.map`

---

## Frontend Environment Variables

Set in `frontend/.env` (or `.env.local`):
- `VITE_API_BASE_URL=http://localhost:8000`
- `VITE_API_BASE=http://localhost:8000`
- `VITE_ENABLE_LIVE_API=true`
- `VITE_LOCAL_DATA_ONLY=false`

---

## Technical Checklist Mapping

- Accuracy target (`<=5%` error):
  - `mape` metric emitted from interpolation run.
- Anomaly precision target (`>=90%`):
  - seasonal-rule precision metric emitted.
- Scalability:
  - Leaflet/react-leaflet dashboard path + Three.js 3D aquifer rendering.
- Government integration:
  - secured APIs, GeoJSON outputs, WMS/WFS server support, PDF exports.

---

## Deterministic Bootstrap (File -> Postgres)

The project supports deterministic, idempotent bootstrap ingestion using:

```bash
python -m scripts.bootstrap_postgres_from_files
```

Input priority is locked to:
1. `frontend/public/data/*.json`
2. `output/final_dataset.csv`
3. `data/exports/map_data.geojson`

Environment variables:
- `BOOTSTRAP_MODE` (`full` or `update`)
- `BOOTSTRAP_ADMIN_USERNAME`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `DATA_VERSION` (optional)

Compose runs the bootstrap as a one-shot `bootstrap` service before backend startup.

---

## Geospatial Groundwater Prediction Pipeline

This repo includes a modular village-level geospatial prediction workflow under `groundwater_pipeline/`:

- `groundwater_pipeline/data/`: file loading and normalization (`geopandas` + `pandas`)
- `groundwater_pipeline/processing/`: village mapping and feature engineering
- `groundwater_pipeline/models/`: XGBoost model and IDW interpolation baseline
- `groundwater_pipeline/visualization/`: Folium map and time slider export

Run:

```bash
python -m groundwater_pipeline.run_pipeline --raw-dir data/raw --predictions-out output/groundwater_predictions.csv --map-out output/groundwater_map.html
```

Outputs:

- `output/groundwater_predictions.csv`
- `output/groundwater_model_metrics.csv`
- `output/groundwater_map.html`
