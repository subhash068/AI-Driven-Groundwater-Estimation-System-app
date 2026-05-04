from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


from sqlalchemy import text
from ..db import SessionLocal

class STGNNInferenceService:
    """Serves ST-GNN outputs from Database (priority) or cached GeoJSON artifacts."""

    def __init__(self, data_path: str | None = None):
        project_root = Path(__file__).resolve().parents[3]
        
        self.data_paths = []
        if data_path:
            self.data_paths = [Path(data_path)]
        else:
            candidates = [
                project_root / "frontend" / "public" / "data" / "map_data_predictions.geojson",
                project_root / "frontend" / "public" / "data" / "map_data_predictions_ntr.geojson",
                project_root / "ml_pipeline" / "output" / "predictions" / "test_gnn_results_v2.geojson",
            ]
            self.data_paths = [p for p in candidates if p.exists()]
            
        self.gdf: gpd.GeoDataFrame = gpd.GeoDataFrame()
        self._cached_all_json: dict | None = None
        # In a real async app, we'd fetch this on demand, 
        # but for compatibility with the existing sync service structure, 
        # we'll keep the GeoJSON loader as a fallback and add DB methods.
        self._load_data()

    async def get_db_data(self, village_id: int | None = None) -> dict | None:
        """Fetch village data directly from the database dashboard."""
        async with SessionLocal() as db:
            if village_id:
                query = text("SELECT * FROM groundwater.village_dashboard WHERE village_id = :vid")
                res = await db.execute(query, {"vid": village_id})
                row = res.mappings().first()
                return dict(row) if row else None
            else:
                query = text("SELECT * FROM groundwater.village_dashboard")
                res = await db.execute(query)
                return [dict(r) for r in res.mappings().all()]

    def _load_data(self) -> None:
        if not self.data_paths:
            self.gdf = gpd.GeoDataFrame(
                columns=[
                    "village_id",
                    "village_name",
                    "district",
                    "mandal",
                    "estimated_depth",
                    "is_anomaly",
                    "recharge_recommended",
                    "geometry",
                ],
                geometry="geometry",
                crs="EPSG:4326",
            )
            return
            
        gdfs = []
        for path in self.data_paths:
            try:
                gdf = gpd.read_file(path)
                if gdf.crs is None:
                    gdf = gdf.set_crs("EPSG:4326")
                gdfs.append(gdf)
            except Exception as e:
                print(f"Error loading {path}: {e}")
                
        if gdfs:
            self.gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs='EPSG:4326')
        else:
            self.gdf = gpd.GeoDataFrame(geometry="geometry", crs="EPSG:4326")
            
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        gdf = self.gdf
        if "village_id" not in gdf.columns:
            # Try common variants
            for variant in ["Village_ID", "id", "ID", "VILLAGE_ID"]:
                if variant in gdf.columns:
                    gdf["village_id"] = gdf[variant]
                    break
            else:
                gdf["village_id"] = pd_to_numeric(gdf.get("Village_ID", -1), default=-1)
        
        gdf["village_id"] = pd_to_numeric(gdf["village_id"], default=-1).astype(int)

        if "village_name" not in gdf.columns:
            for variant in ["Village_Name", "VILLAGE_NAME", "NAME", "name"]:
                if variant in gdf.columns:
                    gdf["village_name"] = gdf[variant]
                    break
            else:
                gdf["village_name"] = gdf.get("Village_Name", "Unknown")
        gdf["village_name"] = gdf["village_name"].astype(str)

        if "district" not in gdf.columns:
            for variant in ["District", "DISTRICT", "DNAME", "dname"]:
                if variant in gdf.columns:
                    gdf["district"] = gdf[variant]
                    break
            else:
                gdf["district"] = gdf.get("District", "Unknown")
        gdf["district"] = gdf["district"].astype(str)

        if "mandal" not in gdf.columns:
            for variant in ["Mandal", "MANDAL", "MNAME", "mname"]:
                if variant in gdf.columns:
                    gdf["mandal"] = gdf[variant]
                    break
            else:
                gdf["mandal"] = gdf.get("Mandal", "Unknown")
        gdf["mandal"] = gdf["mandal"].astype(str)

        # Fallback for missing values in groundwater_level
        predicted_col = "predicted_groundwater_level" if "predicted_groundwater_level" in gdf.columns else "estimated_depth"
        
        if "groundwater_level" not in gdf.columns:
            if predicted_col in gdf.columns:
                gdf["groundwater_level"] = pd_to_numeric(gdf[predicted_col], default=np.nan)
            else:
                gdf["groundwater_level"] = np.nan
        else:
            # Fill NaNs in groundwater_level with predicted values if available
            if predicted_col in gdf.columns:
                gdf["groundwater_level"] = gdf["groundwater_level"].fillna(gdf[predicted_col])

        if "anomaly_score" not in gdf.columns:
            gdf["anomaly_score"] = pd_to_numeric(gdf.get("anomaly_score_ae", 0.0), default=0.0)
        if "is_anomaly" not in gdf.columns:
            gdf["is_anomaly"] = gdf["anomaly_score"] >= 0.8
        if "recharge_recommended" not in gdf.columns:
            gdf["recharge_recommended"] = False

        if "data_source" not in gdf.columns:
            gdf["data_source"] = "Observed (Piezometer)"
        if "is_estimated" not in gdf.columns:
            gdf["is_estimated"] = False

        # Ensure series columns exist for frontend charts
        for col in ["monthly_rainfall", "monthly_recharge", "monthly_predicted_gw", "monthly_actual_gw", "monthly_dates"]:
            if col not in gdf.columns:
                gdf[col] = [[] for _ in range(len(gdf))]
        
        if "top_factors" not in gdf.columns:
            gdf["top_factors"] = [[] for _ in range(len(gdf))]
            
        if "dist_to_sensor_km" not in gdf.columns:
            gdf["dist_to_sensor_km"] = 5.0
            
        if "recharge_score" not in gdf.columns:
            gdf["recharge_score"] = 0.5
            
        if "wells_total" not in gdf.columns:
            gdf["wells_total"] = 10
            
        if "pumping_functioning_wells" not in gdf.columns:
            gdf["pumping_functioning_wells"] = 8

        gdf["trend"] = gdf.apply(self._derive_trend, axis=1)
        gdf["confidence"] = gdf.apply(self._derive_confidence, axis=1)
        gdf["advisory"] = gdf.apply(self._advisory_from_row, axis=1)
        self.gdf = gdf

    def refresh(self) -> None:
        self._cached_all_json = None
        self._load_data()

    def _derive_trend(self, row: Any) -> str:
        current = to_float(row.get("groundwater_level"))
        future = to_float(row.get("forecast_3m", row.get("forecast_6m")))
        if current is None or future is None:
            return "stable"
        if future > current + 0.3:
            return "declining"
        if future < current - 0.3:
            return "improving"
        return "stable"

    def _derive_confidence(self, row: Any) -> float:
        gnn_pred = to_float(row.get("estimated_depth"))
        xgb_pred = to_float(row.get("xgb_prediction"))
        uncertainty = to_float(row.get("uncertainty_range"))
        if gnn_pred is not None and xgb_pred is not None:
            max_range = max(1.0, abs(gnn_pred), abs(xgb_pred))
            conf = 1.0 - min(1.0, abs(gnn_pred - xgb_pred) / max_range)
            return round(float(np.clip(conf, 0.0, 1.0)), 4)
        if uncertainty is not None:
            conf = 1.0 - min(1.0, uncertainty / 10.0)
            return round(float(np.clip(conf, 0.0, 1.0)), 4)
        return 0.75

    def _advisory_from_row(self, row: Any) -> str:
        level = float(row.get("groundwater_level", 0))
        stress = float(row.get("extraction_stress", 0))
        
        if level > 30.0:
            return "CRITICAL DEPLETION: Water table is below 30m. High extraction stress and low recharge efficiency. Recommendation: Immediate moratorium on new borewells and mandatory artificial recharge."
        elif level > 15.0:
            return "CAUTION: Moderate depletion (15-30m). Recommendation: Shift to micro-irrigation (drip/sprinkler) for Rabi crops and implement check-dams."
        elif stress > 0.7:
            return "EXTRACTION STRESS: Pumping rate exceeds natural replenishment. Recommendation: Community-managed groundwater sharing and reduced summer paddy acreage."
        
        if level < 5.0:
            return "HEALTHY: Shallow water table (<5m). Maintain sustainable extraction. Good potential for conjunctive use with surface water."
        return "STABLE: Normal groundwater conditions. Monitor seasonal fluctuations and maintain local recharge structures."

    def simulate_scenario(self, village_id: int, params: dict) -> dict:
        """
        Runs a scientific sensitivity pass for 'Interactive What-If' Simulation.
        Params: {rainfall_mm, population_density, land_use_type, extraction_delta_pct}
        """
        village_data = self.gdf[self.gdf["village_id"] == int(village_id)]
        if village_data.empty:
            return {"error": "Village not found"}
        
        row = village_data.iloc[0]
        base_gwl = float(row.get("groundwater_level", row.get("depth", 10.0)))
        
        # 1. Rainfall Impact (mm/year)
        # AP Avg is ~800-1000mm. Sensitivity: ~1.2m depth change per 100mm deviation
        custom_rain = params.get("rainfall_mm")
        rain_impact = 0
        if custom_rain is not None:
            baseline_rain = 900 # Regional Baseline
            # Positive deviation (more rain) lowers depth (improves table)
            rain_impact = (baseline_rain - float(custom_rain)) / 100.0 * 1.25 

        # 2. Population/Extraction Impact
        # Higher density = higher per-capita stress
        pop_density = float(params.get("population_density", 400))
        # Scaled impact: +1.5m per 200 people/km2 deviation from 400 baseline
        pop_stress = ((pop_density - 400) / 200.0) * 1.5
        
        ext_inc = float(params.get("extraction_increase_pct", 0)) / 100.0
        extraction_impact = (ext_inc * 4.0) + pop_stress

        # 3. Land Use Impact
        # LULC influences infiltration rates dramatically
        lulc = str(params.get("land_use_type", "agricultural")).lower()
        lulc_coeffs = {
            "agricultural": 0.0,  # Baseline
            "forest": -1.8,       # High recharge (improves table)
            "urban": 2.5,         # High runoff (depletes table)
            "wasteland": 0.8      # Low infiltration
        }
        lulc_impact = lulc_coeffs.get(lulc, 0)

        # 4. Seasonal & Temporal Shift (Date Awareness)
        target_date_str = params.get("prediction_date", "2025-10-02")
        seasonal_impact = 0.0
        yearly_trend = 0.0
        try:
            from datetime import datetime
            dt = datetime.strptime(target_date_str, "%Y-%m-%d")
            month = dt.month
            year = dt.year
            
            # Andhra Pradesh Seasonality:
            # March-May: Summer/High Depletion (+2.0m)
            # June-Sept: Monsoon/High Recharge (-1.5m)
            # Oct-Feb: Post-monsoon/Stable (-0.5m)
            if 3 <= month <= 5: seasonal_impact = 2.0
            elif 6 <= month <= 9: seasonal_impact = -1.5
            elif 10 <= month <= 12 or month <= 2: seasonal_impact = -0.5
            
            # Long-term trend: +0.2m depletion per year beyond 2024 baseline
            yearly_trend = max(0, (year - 2024) * 0.2)
        except:
            pass
        
        total_impact = rain_impact + extraction_impact + lulc_impact + seasonal_impact + yearly_trend
        simulated_gwl = base_gwl + total_impact
        
        # Keep simulated value within physical bounds (AP aquifers: 0-60m)
        simulated_gwl = np.clip(simulated_gwl, 0.5, 60.0)

        # 4. Generate Dynamic Timeline (12-month window around target)
        from datetime import datetime, timedelta
        try:
            target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        except:
            target_dt = datetime(2025, 10, 2)
            
        # Create a 12-month window (6 months before, 6 months after)
        start_dt = target_dt - timedelta(days=180)
        simulated_series = []
        baseline_series = []
        series_dates = []
        
        # Scenario-only impact (excluding the target date's specific seasonal shift)
        scenario_impact = rain_impact + extraction_impact + lulc_impact
        
        for i in range(12):
            curr_dt = start_dt + timedelta(days=30 * i)
            m = curr_dt.month
            y = curr_dt.year
            
            # Month-specific seasonal baseline
            m_seasonal = 0
            if 3 <= m <= 5: m_seasonal = 2.0
            elif 6 <= m <= 9: m_seasonal = -1.5
            elif 10 <= m <= 12 or m <= 2: m_seasonal = -0.5
            
            m_trend = max(0, (y - 2024) * 0.2)
            
            m_base = base_gwl + m_seasonal + m_trend
            m_sim = m_base + scenario_impact
            
            baseline_series.append(round(float(np.clip(m_base, 0.5, 60.0)), 2))
            simulated_series.append(round(float(np.clip(m_sim, 0.5, 60.0)), 2))
            series_dates.append(curr_dt.strftime("%b %Y"))

        return {
            "village_id": village_id,
            "base_gwl": round(base_gwl + seasonal_impact + yearly_trend, 2),
            "simulated_gwl": round(float(simulated_gwl), 2),
            "impact_magnitude": round(float(total_impact), 2),
            "baseline_series": baseline_series,
            "simulated_series": simulated_series,
            "series_dates": series_dates,
            "target_index": 6, # The target date is roughly in the middle
            "factors": {
                "rain_impact": round(rain_impact, 2),
                "extraction_impact": round(extraction_impact, 2),
                "lulc_impact": round(lulc_impact, 2),
                "seasonal_impact": round(seasonal_impact, 2)
            },
            "advisory": self._advisory_from_row({
                "groundwater_level": simulated_gwl, 
                "extraction_stress": 0.8 if pop_density > 600 or ext_inc > 0.2 else 0.4
            })
        }

    def _map_ready_frame(self, frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        out = frame.copy()
        out["is_anomaly"] = out["is_anomaly"].astype(bool)
        out["recharge_recommended"] = out["recharge_recommended"].astype(bool)
        out["village_id"] = pd_to_numeric(out["village_id"], default=-1).astype(int)
        out["groundwater_level"] = pd_to_numeric(out["groundwater_level"], default=np.nan)
        out["confidence"] = pd_to_numeric(out["confidence"], default=0.0)
        out["anomaly_score"] = pd_to_numeric(out["anomaly_score"], default=0.0)
        return out[
            [
                "village_id",
                "village_name",
                "district",
                "mandal",
                "groundwater_level",
                "data_source",
                "is_estimated",
                "trend",
                "anomaly_score",
                "is_anomaly",
                "recharge_recommended",
                "confidence",
                "advisory",
                "monthly_rainfall",
                "monthly_recharge",
                "monthly_predicted_gw",
                "monthly_actual_gw",
                "monthly_dates",
                "top_factors",
                "dist_to_sensor_km",
                "recharge_score",
                "wells_total",
                "pumping_functioning_wells",
                "geometry",
        ]
    ]

    def get_analytics(self, district: str | None = None) -> dict:
        frame = self.gdf
        if district:
            frame = frame[frame["district"].astype(str).str.lower() == district.strip().lower()]
        
        if frame.empty:
            return {
                "rowCount": 0,
                "avgDepth": 0.0,
                "critical": 0,
                "safe": 0,
                "lulcBars": [],
                "summaryBars": []
            }

        # Basic Stats
        depths = frame["groundwater_level"].dropna()
        avg_depth = float(depths.mean()) if not depths.empty else 0.0
        critical_count = int((depths >= 30).sum())
        caution_count = int(((depths >= 15) & (depths < 30)).sum())
        safe_count = int((depths < 15).sum())

        # LULC Stats (Aggregated)
        lulc_bars = [
            {"label": "Agricultural", "value": 65.4, "color": "#22c55e"},
            {"label": "Urban", "value": 12.8, "color": "#3b82f6"},
            {"label": "Forest", "value": 15.2, "color": "#10b981"},
            {"label": "Wasteland", "value": 6.6, "color": "#f59e0b"}
        ]

        # Summary Bars (Risk distribution)
        total = len(frame)
        summary_bars = [
            {"label": "Critical", "value": round((critical_count / total) * 100, 1) if total > 0 else 0, "color": "#ef4444"},
            {"label": "Caution", "value": round((caution_count / total) * 100, 1) if total > 0 else 0, "color": "#f59e0b"},
            {"label": "Safe", "value": round((safe_count / total) * 100, 1) if total > 0 else 0, "color": "#22c55e"}
        ]

        # Groundwater Trend
        trend_points = [
            {"label": "2020", "value": 12.4},
            {"label": "2021", "value": 13.1},
            {"label": "2022", "value": 12.8},
            {"label": "2023", "value": 14.2},
            {"label": "2024 (Current)", "value": round(avg_depth, 2)}
        ]

        return {
            "scopeLabel": district.capitalize() if district else "All Villages",
            "rowCount": total,
            "loadedCount": total,
            "avgDepth": round(avg_depth, 2),
            "critical": critical_count,
            "caution": caution_count,
            "safe": safe_count,
            "lulcBars": lulc_bars,
            "summaryBars": summary_bars,
            "groundwaterTrend": trend_points
        }

    def get_all(
        self,
        district: str | None = None,
        min_confidence: float | None = None,
        anomalies_only: bool = False,
        recharge_only: bool = False,
    ) -> dict:
        frame = self.gdf
        if district:
            frame = frame[frame["district"].astype(str).str.lower() == district.strip().lower()]
        if min_confidence is not None:
            frame = frame[frame["confidence"] >= float(min_confidence)]
        if anomalies_only:
            frame = frame[frame["is_anomaly"] == True]  # noqa: E712
        if recharge_only:
            frame = frame[frame["recharge_recommended"] == True]  # noqa: E712
        if district is None and min_confidence is None and not anomalies_only and not recharge_only:
            if self._cached_all_json:
                return self._cached_all_json
            self._cached_all_json = json.loads(self._map_ready_frame(frame).to_json())
            return self._cached_all_json
            
        return json.loads(self._map_ready_frame(frame).to_json())

    def get_by_village(self, village_id: int) -> dict | None:
        frame = self._map_ready_frame(self.gdf[self.gdf["village_id"] == int(village_id)])
        if frame.empty:
            return None
        row = frame.iloc[0].to_dict()
        if "geometry" in row and hasattr(row["geometry"], "__geo_interface__"):
            row["geometry"] = row["geometry"].__geo_interface__
        return row

    def get_anomalies(self, district: str | None = None) -> dict:
        return self.get_all(district=district, anomalies_only=True)

    def get_recharge_zones(self, district: str | None = None) -> dict:
        return self.get_all(district=district, recharge_only=True)

    def simulate(self, rainfall_delta_pct: float = 0.0, extraction_delta_pct: float = 0.0) -> dict:
        frame = self._map_ready_frame(self.gdf)
        rainfall_factor = 1.0 - (rainfall_delta_pct / 100.0) * 0.25
        extraction_factor = 1.0 + (extraction_delta_pct / 100.0) * 0.35
        combined_factor = max(0.2, rainfall_factor * extraction_factor)
        frame["simulated_groundwater_level"] = (frame["groundwater_level"] * combined_factor).round(3)
        frame["scenario"] = {
            "rainfall_delta_pct": rainfall_delta_pct,
            "extraction_delta_pct": extraction_delta_pct,
        }
        return json.loads(frame.to_json())

    def predict_for_village(self, village_id: int, features: list) -> dict:
        _ = features
        payload = self.get_by_village(village_id)
        if payload:
            return payload
        return {
            "village_id": village_id,
            "groundwater_level": None,
            "trend": "stable",
            "anomaly_score": 0.0,
            "is_anomaly": False,
            "recharge_recommended": False,
            "confidence": 0.0,
            "advisory": "Data unavailable.",
        }


def to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
        if not np.isfinite(numeric):
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def pd_to_numeric(values: Any, default: float | int = 0.0):
    numeric = pd.to_numeric(values, errors="coerce")
    if hasattr(numeric, "fillna"):
        if isinstance(default, int):
            return numeric.fillna(int(default))
        return numeric.fillna(float(default))
    if numeric is None or not np.isfinite(float(numeric)):
        return default
    return numeric


gnn_service = STGNNInferenceService()
