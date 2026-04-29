### Krishna Groundwater AI v2 Implementation Plan

#### Summary
- Build a new non-breaking `v2` pipeline and UI path on top of the existing repo: keep current features running, add a production-ready village groundwater estimation system with FastAPI + XGBoost + Kriging, and React + Leaflet + Tailwind map dashboard.
- Use repository-staged raw inputs in `data/raw` as the single source of truth, including your provided ZIP/XLSX files.
- Default modeling mode will support both kriging strategies via config, with **hybrid selectable** behavior (`residual` or `direct`) and residual-kriging as default runtime strategy unless overridden.

#### Key Changes
- Backend/data pipeline:
  - Add a deterministic ingestion + feature pipeline that unzips/reads LULC, villages, aquifer/wells/DEM/soil, piezometer, and pumping files; reprojects to a common CRS; clips LULC to village boundaries; computes class percentages; drops `Clouds` and `Snow/Ice`.
  - Compute derived features exactly as requested:
    - `infiltration_score = water_pct*0.9 + trees_pct*0.8 + crops_pct*0.6 - built_pct*0.9`
    - `groundwater_stress = pumping_rate / recharge_factor`
  - Build a single village-level training table combining LULC features + pumping + piezometer + hydrogeology (+ rainfall when available; fallback to optional synthetic/empty column policy with warnings, not silent failure).
  - Train and persist XGBoost artifacts (`model`, `feature schema`, `metrics`, `run metadata`) under `model/artifacts/`.
  - Add kriging module using GSTools/PyKrige with strategy flag:
    - `residual`: krige residuals and add correction to XGBoost predictions.
    - `direct`: krige groundwater target directly.
- API surface (new v2 endpoints; existing endpoints untouched):
  - `GET /v2/predict?village_id=...` → village prediction payload with groundwater level, confidence, risk bucket, and feature snapshot.
  - `GET /v2/map-data` → FeatureCollection of villages with prediction + LULC percentages + risk + change indicators.
  - `GET /v2/lulc-trends` → village trend metrics for built-up change and groundwater change (enabled only when multi-year LULC snapshots are present).
  - `POST /v2/retrain` (admin/dev mode) → trigger model rebuild from staged data and refresh artifacts.
- Frontend (new dashboard route/view, Leaflet + Tailwind):
  - Add Tailwind setup and a new groundwater map dashboard page (no regression to existing page).
  - Render village boundary choropleth for groundwater predictions with click popups showing groundwater level, LULC distribution percentages, and risk level.
  - Add LULC overlay layer + interactive legend with exact fixed mapping:
    - Water `#3b82f6`, Trees `#22c55e`, Flooded Vegetation `#86efac`, Crops `#facc15`, Built Area `#ef4444`, Bare Ground `#d4d4d4`, Snow/Ice `#e5e7eb`, Clouds `#9ca3af`, Rangeland `#fcd34d`
  - Add class visibility toggles and filters:
    - high-risk villages only
    - selected LULC class visibility
  - Add advanced analytics panel:
    - time-series comparison for LULC (when multiple vintages found)
    - highlight villages with built-up increase + groundwater decline
- Project structure alignment:
  - Keep requested top-levels active and explicit:
    - `frontend/` (React + Tailwind + Leaflet dashboard v2)
    - `backend/` (FastAPI v2 APIs + inference service)
    - `model/` (training, feature engineering, interpolation scripts, artifacts)
  - Add reproducible data directories: `data/raw`, `data/processed`, `data/exports`.

#### Test Plan
- Data pipeline tests:
  - Validate class-percentage totals per village (`~100%` after noise-class exclusion handling).
  - Validate joins/keys across village IDs and missing-value policies.
  - Validate derived feature equations with deterministic fixtures.
- Model/interpolation tests:
  - Train smoke test on sample subset.
  - Inference contract test for both kriging modes.
  - Metrics output test (MAE/RMSE/R2 + artifact manifest presence).
- API tests:
  - `GET /v2/predict` valid/invalid `village_id`.
  - `GET /v2/map-data` GeoJSON schema and required properties.
  - `GET /v2/lulc-trends` behavior with and without multi-year LULC.
- Frontend tests:
  - Legend rendering and exact color mapping assertions.
  - Layer toggle/filter behavior.
  - Popup content correctness for clicked village.
  - End-to-end API integration smoke using local backend.

#### Assumptions
- Source files will be copied into repo `data/raw` and referenced by relative config.
- Multi-year LULC trend features are enabled only if multiple dated LULC snapshots are detected; otherwise UI shows “trend unavailable” state (not fake trend values).
- Existing legacy endpoints and UI remain operational; new functionality ships under `v2` namespace/routes.
- Local run instructions will include one-command backend startup, model build/retrain commands, and frontend dev server steps with environment templates.
