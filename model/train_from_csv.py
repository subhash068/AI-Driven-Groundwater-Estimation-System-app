import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from ml.generate_dataset import load_villages


def _normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def _aquifer_storage_factor(value: object) -> float:
    text = _normalize_text(value)
    if not text or text == "unknown":
        return 1.0

    if any(term in text for term in ("alluvium", "alluvial", "valley fill", "sandstone", "limestone", "shale", "unconsolidated")):
        return 1.35
    if any(term in text for term in ("laterite", "pediment", "weathered")):
        return 1.1
    if any(term in text for term in ("granite", "gneiss", "charnokite", "basalt", "quartzite", "schist", "khondalite")):
        return 0.7
    return 1.0


def _canonicalize_dataset_columns(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "Village_ID": ["Village_ID", "village_id"],
        "Village_Name": ["Village_Name", "village_name"],
        "District": ["District", "district"],
        "Mandal": ["Mandal", "mandal"],
        "State": ["State", "state"],
        "Water%": ["Water%", "water_pct", "water"],
        "Trees%": ["Trees%", "trees_pct", "trees"],
        "Crops%": ["Crops%", "crops_pct", "crops"],
        "Built%": ["Built%", "built_area_pct", "built"],
        "Bare%": ["Bare%", "bare_ground_pct", "bare"],
        "Rangeland%": ["Rangeland%", "rangeland_pct", "rangeland"],
        "Pumping": ["Pumping", "pumping_rate", "pumping"],
        "GW_Level": ["GW_Level", "gw_level", "depth"],
        "Soil": ["Soil", "soil"],
        "Elevation": ["Elevation", "elevation"],
    }
    rename: dict[str, str] = {}
    available = {str(col).strip().lower(): col for col in df.columns}
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            key = str(candidate).strip().lower()
            if key in available:
                original = available[key]
                if original != canonical:
                    rename[original] = canonical
                break
    if rename:
        df = df.rename(columns=rename)
    return df


def _ensure_dirs(repo_root: Path) -> tuple[Path, Path]:
    exports_dir = repo_root / "data" / "exports"
    artifacts_dir = repo_root / "model" / "artifacts"
    exports_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return exports_dir, artifacts_dir


def _bounded_inverse(values: np.ndarray) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    if finite.size == 0:
        return finite
    upper = float(np.nanquantile(finite, 0.9)) if np.isfinite(finite).any() else 0.0
    if not np.isfinite(upper) or upper <= 0:
        return np.ones(len(finite), dtype=float)
    return np.clip(1.0 - (finite / upper), 0.0, 1.0)


def _bounded_forward(values: np.ndarray) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    if finite.size == 0:
        return finite
    upper = float(np.nanquantile(finite, 0.9)) if np.isfinite(finite).any() else 0.0
    if not np.isfinite(upper) or upper <= 0:
        return np.ones(len(finite), dtype=float)
    return np.clip(finite / upper, 0.0, 1.0)


def _compute_confidence_support(
    centroids_area: gpd.GeoSeries,
    observed_mask: pd.Series,
    predictions: np.ndarray,
    radius_km: float = 15.0,
    neighbor_k: int = 5,
) -> pd.DataFrame:
    coords = np.column_stack([centroids_area.x.values, centroids_area.y.values]).astype(float)
    n = len(coords)
    obs_mask = observed_mask.fillna(False).to_numpy(dtype=bool)
    dist_matrix_m = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
    radius_m = radius_km * 1000.0

    nearest_distance_km = np.zeros(n, dtype=float)
    nearby_obs_count = np.zeros(n, dtype=float)
    local_pred_var = np.zeros(n, dtype=float)

    obs_indices = np.flatnonzero(obs_mask)
    for i in range(n):
        if obs_indices.size:
            obs_distances = dist_matrix_m[i, obs_indices].copy()
            if obs_mask[i]:
                obs_distances[obs_distances == 0.0] = np.inf
            finite_obs = obs_distances[np.isfinite(obs_distances)]
            nearest_distance_km[i] = float(finite_obs.min() / 1000.0) if finite_obs.size else 0.0

            nearby_mask = dist_matrix_m[i, obs_indices] <= radius_m
            nearby_obs_count[i] = float(nearby_mask.sum())
            if obs_mask[i] and nearby_obs_count[i] > 0:
                nearby_obs_count[i] -= 1.0
        else:
            nearest_distance_km[i] = radius_km
            nearby_obs_count[i] = 0.0

        order = np.argsort(dist_matrix_m[i])
        neighbor_ids = [idx for idx in order if idx != i][:neighbor_k]
        if neighbor_ids:
            local_pred_var[i] = float(np.var(predictions[neighbor_ids]))
        else:
            local_pred_var[i] = 0.0

    distance_component = _bounded_inverse(nearest_distance_km)
    density_component = _bounded_forward(nearby_obs_count)
    variance_component = _bounded_inverse(local_pred_var)
    confidence = np.clip(
        0.45 * distance_component + 0.35 * density_component + 0.20 * variance_component,
        0.0,
        1.0,
    )

    return pd.DataFrame(
        {
            "nearest_piezometer_distance_km": nearest_distance_km,
            "nearby_observation_count": nearby_obs_count.astype(int),
            "neighboring_prediction_variance": local_pred_var,
            "confidence_distance_component": distance_component,
            "confidence_density_component": density_component,
            "confidence_variance_component": variance_component,
            "confidence": confidence,
        }
    )


def _prepare_training_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frame = df.copy()

    numeric_cols = [
        "Water%",
        "Trees%",
        "Crops%",
        "Built%",
        "Bare%",
        "Rangeland%",
        "Pumping",
        "pumping_functioning_wells",
        "pumping_monsoon_draft_ha_m",
        "GW_Level",
        "Elevation",
        "tank_count",
        "wells_total",
        "elevation_min",
        "elevation_max",
        "flooded_vegetation_pct",
        "obs_station_count",
        "long_term_avg",
        "trend_slope",
        "seasonal_variation",
    ]
    for col in numeric_cols:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        else:
            frame[col] = 0.0

    frame["Soil"] = frame.get("Soil", "Unknown").fillna("Unknown").astype(str)
    frame["aquifer_type"] = frame.get("aquifer_type", "Unknown").fillna("Unknown").astype(str)
    frame["rainfall_proxy"] = frame["flooded_vegetation_pct"].fillna(0.0)
    frame["recharge_index"] = frame["Water%"] + frame["tank_count"] + frame["rainfall_proxy"]
    frame["pumping_norm"] = (
        frame["Pumping"] / (frame["wells_total"] + 1.0)
    ).replace([np.inf, -np.inf], 0).fillna(0.0)
    frame["draft_per_well"] = (
        frame["pumping_monsoon_draft_ha_m"] / (frame["pumping_functioning_wells"] + 1.0)
    ).replace([np.inf, -np.inf], 0).fillna(0.0)
    frame["extraction_stress"] = (
        frame["pumping_norm"]
    ).replace([np.inf, -np.inf], 0).fillna(0.0)
    frame["terrain_gradient"] = (frame["elevation_max"] - frame["elevation_min"]).fillna(0.0)
    frame["aquifer_storage_factor"] = frame["aquifer_type"].map(_aquifer_storage_factor).astype(float)
    frame["recharge_factor"] = (
        0.3
        + frame["Water%"] * 0.01
        + frame["Trees%"] * 0.008
        + frame["Rangeland%"] * 0.005
        + frame["Bare%"] * 0.002
        - frame["Built%"] * 0.006
    ).clip(lower=0.1, upper=3.0)
    frame["infiltration_score"] = (
        frame["Water%"] * 0.9
        + frame["Trees%"] * 0.8
        + frame["Crops%"] * 0.6
        - frame["Built%"] * 0.9
    )
    frame["groundwater_stress"] = (frame["Pumping"] / frame["recharge_factor"]).replace([np.inf, -np.inf], 0).fillna(0)

    base_features = [
        "Water%",
        "Trees%",
        "Crops%",
        "Built%",
        "Bare%",
        "Rangeland%",
        "Pumping",
        "pumping_functioning_wells",
        "pumping_monsoon_draft_ha_m",
        "Elevation",
        "infiltration_score",
        "recharge_factor",
        "groundwater_stress",
        "pumping_norm",
        "draft_per_well",
        "recharge_index",
        "extraction_stress",
        "terrain_gradient",
        "aquifer_storage_factor",
        "obs_station_count",
        "long_term_avg",
        "trend_slope",
        "seasonal_variation",
    ]

    encoded = pd.get_dummies(frame[["Soil"]], prefix="soil")
    model_df = pd.concat([frame[["Village_ID", "Village_Name", "GW_Level"] + base_features], encoded], axis=1)
    feature_cols = base_features + list(encoded.columns)
    return model_df, feature_cols


def _risk_labels(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    q1 = float(values.quantile(0.33))
    q2 = float(values.quantile(0.66))

    def classify(v: float) -> str:
        if v <= q1:
            return "Low"
        if v <= q2:
            return "Medium"
        return "High"

    levels = values.map(classify)
    scores = levels.map({"Low": 1, "Medium": 2, "High": 3}).astype(int)
    return levels, scores


def train_from_dataset(dataset_csv: Path, data_dir: Path, repo_root: Path, kriging_strategy: str) -> dict:
    if not dataset_csv.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_csv}")

    exports_dir, artifacts_dir = _ensure_dirs(repo_root)

    df = pd.read_csv(dataset_csv)
    df = _canonicalize_dataset_columns(df)
    required = {"Village_ID", "Village_Name", "Water%", "Trees%", "Crops%", "Built%", "Bare%", "Rangeland%", "Pumping", "GW_Level", "Soil", "Elevation"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")

    model_df, feature_cols = _prepare_training_frame(df)
    X = model_df[feature_cols]
    y = model_df["GW_Level"]
    observed_by_village = (
        pd.DataFrame(
            {
                "Village_ID": pd.to_numeric(df["Village_ID"], errors="coerce"),
                "observed": pd.to_numeric(df["GW_Level"], errors="coerce").notna(),
            }
        )
        .dropna(subset=["Village_ID"])
        .assign(Village_ID=lambda d: d["Village_ID"].astype(int))
        .drop_duplicates(subset=["Village_ID"])
        .set_index("Village_ID")["observed"]
    )

    if len(model_df) >= 20:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    else:
        X_train, X_test, y_train, y_test = X, X, y, y

    model = xgb.XGBRegressor(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        objective="reg:squarederror",
        eval_metric="rmse",
    )
    model.fit(X_train, y_train)

    pred_test = model.predict(X_test)
    pred_full = model.predict(X)

    mae = float(mean_absolute_error(y_test, pred_test))
    rmse = float(np.sqrt(mean_squared_error(y_test, pred_test)))
    r2 = float(r2_score(y_test, pred_test))

    village_zip = data_dir / "Village_Mandal_DEM_Soils_MITanks_Krishna.zip"
    villages = load_villages(village_zip)

    district_col = next((c for c in villages.columns if str(c).strip().lower() in {"district", "dname", "dmname"}), None)
    mandal_col = next((c for c in villages.columns if "mandal" in str(c).strip().lower() or str(c).strip().lower() in {"mname", "taluk"}), None)

    villages_base = villages[["Village_ID", "Village_Name", "geometry"]].copy()
    villages_base["district"] = villages[district_col].astype(str).str.strip() if district_col else "Unknown"
    villages_base["mandal"] = villages[mandal_col].astype(str).str.strip() if mandal_col else "Unknown"

    payload = model_df[
        [
            "Village_ID",
            "Village_Name",
            "Water%",
            "Trees%",
            "Crops%",
            "Built%",
            "Bare%",
            "Rangeland%",
            "Pumping",
            "pumping_functioning_wells",
            "pumping_monsoon_draft_ha_m",
            "infiltration_score",
            "groundwater_stress",
            "pumping_norm",
            "draft_per_well",
            "recharge_index",
            "extraction_stress",
            "terrain_gradient",
            "aquifer_storage_factor",
        ]
    ].copy()
    payload["predicted_groundwater_level"] = pred_full
    payload["risk_score"] = payload["predicted_groundwater_level"] * 5
    payload["risk_level"] = payload["risk_score"].apply(
        lambda x: "high" if x > 60 else "medium" if x > 30 else "low"
    )
    rainfall_factor = pd.to_numeric(payload["Water%"], errors="coerce").fillna(0.0) * 0.01
    pumping_factor = pd.to_numeric(payload["Pumping"], errors="coerce").fillna(0.0) * 0.01
    payload["forecast_3m"] = payload["predicted_groundwater_level"] + rainfall_factor - pumping_factor
    payload["forecast_6m"] = payload["forecast_3m"] + rainfall_factor - pumping_factor
    payload["anomaly_flag"] = "normal"
    payload["recharge_potential"] = "medium"

    merged = villages_base.merge(payload, on=["Village_ID", "Village_Name"], how="left")
    merged = merged.rename(
        columns={
            "Village_ID": "village_id",
            "Village_Name": "village_name",
            "Water%": "water_pct",
            "Trees%": "trees_pct",
            "Crops%": "crops_pct",
            "Built%": "built_area_pct",
            "Bare%": "bare_ground_pct",
            "Rangeland%": "rangeland_pct",
            "Pumping": "pumping_rate",
        }
    )
    merged["flooded_vegetation_pct"] = 0.0
    merged["snow_ice_pct"] = 0.0
    merged["clouds_pct"] = 0.0
    merged["urban_growth_risk_flag"] = False
    merged["district"] = merged["district"].astype(str).str.upper().str.strip()
    merged = merged[merged["district"] == "KRISHNA"].copy()
    if merged.empty:
        raise ValueError("Krishna district filter returned zero villages in train_from_csv")
    assert merged["district"].nunique() == 1

    centroids_area = merged.to_crs(villages.estimate_utm_crs() or "EPSG:32644").centroid
    confidence_support = _compute_confidence_support(
        centroids_area=centroids_area,
        observed_mask=merged["village_id"].map(observed_by_village).fillna(False),
        predictions=merged["predicted_groundwater_level"].to_numpy(dtype=float),
    )
    for col in confidence_support.columns:
        merged[col] = confidence_support[col].values

    map_path = exports_dir / "map_data_predictions.geojson"
    frontend_map_path = repo_root / "frontend" / "public" / "data" / "map_data_predictions.geojson"
    frontend_map_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_file(map_path, driver="GeoJSON")
    merged.to_file(frontend_map_path, driver="GeoJSON")

    trends = merged[["village_id", "village_name", "district"]].copy()
    trends["built_up_change_pct"] = np.nan
    trends["groundwater_change_proxy"] = merged["predicted_groundwater_level"] - float(merged["predicted_groundwater_level"].median())
    trends["urban_growth_risk_flag"] = False
    trends["trend_window"] = "single-snapshot"
    trends["lulc_trend_available"] = False
    trends.to_csv(exports_dir / "lulc_trends.csv", index=False)

    model.save_model(str(artifacts_dir / "model_xgb.json"))
    (artifacts_dir / "feature_columns.json").write_text(json.dumps(feature_cols, indent=2))

    metrics = {
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "rows": int(len(model_df)),
        "source_dataset": str(dataset_csv),
        "kriging_strategy": kriging_strategy,
        "kriging_note": "Model trained from generated CSV. Kriging is not applied in this direct dataset path.",
        "confidence_method": "0.45*distance + 0.35*obs_density + 0.20*inverse_prediction_variance",
        "confidence_radius_km": 15.0,
        "confidence_neighbor_k": 5,
    }
    (artifacts_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (artifacts_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "pipeline": "train_from_csv",
                "dataset": str(dataset_csv),
                "map_output": str(map_path),
                "rows": int(len(model_df)),
                "feature_count": len(feature_cols),
            },
            indent=2,
        )
    )
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train XGBoost from generated village dataset and export map data")
    parser.add_argument("--dataset", type=Path, default=Path("output/final_dataset.csv"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--kriging-strategy", default="residual", choices=["residual", "direct"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    metrics = train_from_dataset(
        dataset_csv=args.dataset,
        data_dir=args.data_dir,
        repo_root=repo_root,
        kriging_strategy=args.kriging_strategy,
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

