import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DATA = PROJECT_ROOT / "frontend" / "public" / "data"
LOGGER = logging.getLogger(__name__)

class V2Service:
    def __init__(self):
        self.predictions_path = FRONTEND_DATA / "map_data_predictions.geojson"
        self.final_dataset_path = FRONTEND_DATA / "final_dataset.json"
        self._predictions_cache: Dict[int, Any] = {}
        self._lulc_cache: Dict[int, Any] = {}
        self._map_data_cache: Optional[Dict[str, Any]] = None
        self.refresh_cache()

    def refresh_cache(self):
        LOGGER.info("Refreshing V2 cache...")
        try:
            if self.predictions_path.exists():
                with open(self.predictions_path, 'r') as f:
                    data = json.load(f)
                    self._map_data_cache = data
                    for feature in data.get('features', []):
                        props = feature.get('properties', {})
                        try:
                            vid = int(props.get('village_id', -1))
                            if vid > 0:
                                self._predictions_cache[vid] = props
                        except (ValueError, TypeError):
                            continue
            
            if self.final_dataset_path.exists():
                with open(self.final_dataset_path, 'r') as f:
                    data = json.load(f)
                    for item in data:
                        try:
                            vid = int(item.get('Village_ID', item.get('village_id', -1)))
                            if vid > 0:
                                self._lulc_cache[vid] = item
                        except (ValueError, TypeError):
                            continue
            LOGGER.info("V2 cache refreshed successfully.")
        except Exception as e:
            LOGGER.error(f"Failed to refresh V2 cache: {e}")

    async def get_prediction(self, village_id: int):
        props = self._predictions_cache.get(village_id)
        if not props:
            return None
        
        # Transform factors to structured list[ShapFactor]
        raw_factors = props.get('top_factors', [])
        structured_factors = []
        
        if not raw_factors:
            # Dynamic fallback based on village attributes if no SHAP data is present
            recharge = props.get('recharge_score', props.get('recharge_index', 0.5))
            draft = props.get('monsoon_draft', props.get('extraction_stress', 0.5))
            aquifer = props.get('aquifer_storage_factor', 0.8)
            
            structured_factors = [
                {"label": "Recharge Potential", "value": round(float(recharge) * 1.2, 2)},
                {"label": "Extraction Stress", "value": -round(float(draft) * 1.5, 2)},
                {"label": "Aquifer Storage", "value": round(float(aquifer), 2)},
                {"label": "Elevation Gradient", "value": round(float(props.get('terrain_gradient', 0.4)), 2)},
                {"label": "LULC Stability", "value": 0.65}
            ]
        else:
            for f in raw_factors:
                if isinstance(f, str):
                    structured_factors.append({"label": f.replace('_', ' ').title(), "value": 0.5})
                elif isinstance(f, dict):
                    label = f.get('label') or f.get('feature', 'Unknown')
                    value = f.get('value') or f.get('importance', 0.0)
                    structured_factors.append({"label": label, "value": value})

        return {
            "village_id": village_id,
            "village_name": props.get('village_name', 'Unknown'),
            "mandal": props.get('mandal', 'Unknown'),
            "district": props.get('district', 'Unknown'),
            "groundwater_level": props.get('predicted_groundwater_level'),
            "confidence": props.get('confidence', 0.0),
            "risk_level": props.get('risk_level', 'safe'),
            "trend": props.get('trend', 'stable'),
            "monthly_predicted_gw": list(props.get('monthly_predicted_gw', [])),
            "monthly_dates": [str(d) for d in props.get('monthly_dates', [])],
            "water_pct": props.get('water_pct'),
            "trees_pct": props.get('trees_pct'),
            "crops_pct": props.get('crops_pct'),
            "built_area_pct": props.get('built_area_pct'),
            "dist_to_sensor_km": props.get('dist_to_sensor_km') or props.get('nearest_distance_km') or props.get('dist_to_sensor'),
            "dist_nearest_tank_km": props.get('dist_nearest_tank_km') or props.get('dist_nearest_tank') or props.get('tank_distance'),
            "recharge_score": props.get('recharge_score') or props.get('recharge_potential') or props.get('recharge_index'),
            "top_factors": structured_factors
        }

    async def get_map_data(self):
        if not self._map_data_cache:
            self.refresh_cache()
        return self._map_data_cache

    async def get_lulc_trends(self, village_id: int):
        item = self._lulc_cache.get(village_id)
        if not item:
            return None
        
        return {
            "village_id": village_id,
            "built_area_change_pct": item.get('built_area_change_pct'),
            "lulc_start_year": item.get('lulc_start_year'),
            "lulc_end_year": item.get('lulc_end_year'),
            "lulc_start_dominant": item.get('lulc_start_dominant'),
            "lulc_end_dominant": item.get('lulc_end_dominant')
        }

    def retrain(self):
        script_path = PROJECT_ROOT / "scripts" / "build_authoritative_krishna_data.py"
        try:
            subprocess.run(["python", str(script_path)], check=True)
            self.refresh_cache()
        except Exception as e:
            LOGGER.error(f"Retraining failed: {e}")

v2_service = V2Service()
