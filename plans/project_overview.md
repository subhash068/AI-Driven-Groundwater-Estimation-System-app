# AI-Driven Groundwater Estimation System: Project Overview

This project is a comprehensive, production-grade platform designed for the **Andhra Pradesh Water Resources Department**. It leverages Artificial Intelligence and Geospatial Data Science to estimate, forecast, and visualize groundwater levels across 18,000+ villages.

## 🌟 Core Features
- **Accurate Estimation**: Village-level groundwater depth estimation using XGBoost and spatial Kriging support (targeting <=5% error).
- **Predictive Forecasting**: 3-month groundwater level forecasts using Prophet and LSTM modules.
- **Anomaly Detection**: Automated identification of seasonal anomalies and potential data errors using Isolation Forest.
- **Interactive Dashboard**: High-performance geospatial visualization using React, Leaflet/react-leaflet, and Three.js (including 3D terrain and aquifer views).
- **Farmer Portal**: Mobile-first portal providing localized advisories, crop recommendations, and GPS-based village status.
- **Enterprise-Grade Backend**: FastAPI-powered REST API with Redis caching, RBAC security, and automated geospatial data serving via GeoServer/MapServer.

---

## 🏗️ Technical Architecture

### 1. Data Layer (`/database`, `/data`)
- **Spatial Database**: PostgreSQL with **PostGIS** for village polygons and piezometer point data.
- **Feature Store**: Specialized schema for ML features (elevation, slope, soil permeability, LULC, rainfall).
- **Data Ingestion**: Automated pipelines for IMD rainfall, piezometer readings, and Sentinel-2 LULC rasters.
- **Staging**: `data/raw` for source Excel/ZIP files and `data/processed` for ML-ready datasets.

### 2. Machine Learning Layer (`/ml`, `/model`)
- **Interpolation Engine**: XGBoost regression with hydrogeological covariates.
- **Forecasting Module**: Time-series prediction using Prophet (long-term) and LSTM (short-term).
- **Training Pipeline**: Automated XGBoost training with data versioning and metrics tracking (`model/pipeline.py`).
- **Geostatistical Support**: Kriging strategies for spatial residual correction.

### 3. Backend API (`/backend`)
- **Framework**: FastAPI (Asynchronous Python).
- **Security**: OAuth2 with JWT tokens and Role-Based Access Control (Viewer, Engineer, Admin).
- **Caching**: Redis layer for high-speed response of common geospatial queries.
- **Exports**: Automated PDF generation for field reports and GeoJSON for GIS integrations.

### 4. Geospatial Serving (`/geoserver`, `/mapserver`)
- **GeoServer**: Automated bootstrap scripts to publish PostGIS layers as WMS/WFS services.
- **MapServer**: Mapfile configuration for high-performance vector/raster serving.

### 5. Frontend Dashboards (`/frontend`)
- **Technologies**: React, Vite, Tailwind CSS, Leaflet/react-leaflet, and Three.js (for 3D).
- **Visuals**: Modern glassmorphism design, temporal sliders (24-month playback), and 3D aquifer stratification.
- **Farmer Portal**: Ultra-lightweight GPS-enabled web app for low-bandwidth environments.

---

## 📂 Key File Map
| Path | Description |
| :--- | :--- |
| `backend/app/main.py` | Core API entry point and routing logic. |
| `frontend/src/App.jsx` | Main React dashboard with Leaflet and Three.js integration. |
| `ml/interpolation_engine.py` | Main AI logic for village-level groundwater estimates. |
| `model/pipeline.py` | Full ML training pipeline (XGBoost + Kriging). |
| `database/phase1-5.sql` | Evolution of the PostGIS database schema. |
| `infra/docker-compose.yml` | Full local stack (DB, Redis, GeoServer). |
| `README.md` | Comprehensive setup and execution guide. |

---

## 🚀 Development Status
- **Backend/Database**: Fully implemented with RBAC and spatial functions.
- **ML Pipeline**: Production-ready for XGBoost training and interpolation.
- **Frontend**: High-fidelity dashboard and farmer portal are operational.
- **Infrastructure**: Dockerized and ready for cloud deployment (Render/Vercel/Self-hosted).
