from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ml_pipeline.data.loaders import load_all_data
from ml_pipeline.features.spatial_mapping import build_mapped_tables
from ml_pipeline.features.feature_engineering import build_monthly_features
from ml_pipeline.models.classical.xgboost_model import train_and_predict_xgboost
from ml_pipeline.models.classical.idw import add_idw_baseline
from ml_pipeline.evaluation.spatial_validation import (
    strict_spatial_temporal_validation,
    build_robustness_reports,
    build_judge_summary,
)
from ml_pipeline.evaluation.map_view import build_map
from ml_pipeline.evaluation.schema_validation import validate_schema_dataframe
from ml_pipeline.inference.schema_adapter import normalize_prediction_dataframe
import json
import shutil


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Geospatial groundwater prediction pipeline")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"), help="Directory containing source files")
    parser.add_argument(
        "--predictions-out",
        type=Path,
        default=Path("output/groundwater_predictions.csv"),
        help="CSV output for monthly village predictions",
    )
    parser.add_argument(
        "--map-out",
        type=Path,
        default=Path("output/groundwater_map.html"),
        help="HTML output path for interactive map",
    )
    return parser.parse_args()


def run(raw_dir: Path, predictions_out: Path, map_out: Path) -> None:
    loaded = load_all_data(raw_dir=raw_dir)
    mapped = build_mapped_tables(loaded)

    features = build_monthly_features(
        villages=mapped["villages"],  # type: ignore[arg-type]
        mapped=mapped,
        canals=loaded.canals,
        streams=loaded.streams,
        tanks=loaded.tanks,
        pumping=loaded.pumping,
    )

    model_output = train_and_predict_xgboost(features)
    with_idw = add_idw_baseline(
        village_month_predictions=model_output.village_month_predictions,
        villages=mapped["villages"],  # type: ignore[arg-type]
        piezo_with_village=mapped["piezometer_village"],  # type: ignore[arg-type]
    )

    # Time leakage guardrails: lags must only come from previous months.
    leak_check = with_idw.sort_values(["village_id", "date"]).copy()
    leak_check["prev_obs"] = leak_check.groupby("village_id")["groundwater_level"].shift(1)
    suspect = (leak_check["gw_lag_1"].notna()) & (leak_check["prev_obs"].notna()) & (
        np.abs(pd.to_numeric(leak_check["gw_lag_1"], errors="coerce") - pd.to_numeric(leak_check["prev_obs"], errors="coerce")) > 1e-6
    )
    leakage_flag = int(suspect.sum())

    predictions_out.parent.mkdir(parents=True, exist_ok=True)
    # Keep the main CSV compact to avoid disk pressure on long village-month runs.
    compact_cols = [
        "village_id",
        "date",
        "rainfall",
        "rainfall_3m_sum",
        "rainfall_6m_sum",
        "rainfall_anomaly",
        "groundwater_level",
        "gw_lag_1",
        "gw_lag_2",
        "gw_lag_3",
        "predicted_groundwater_xgb",
        "predicted_groundwater_idw",
        "confidence_score",
        "confidence_level",
        "uncertainty_std_nearby",
        "has_piezometer",
    ]
    write_cols = [col for col in compact_cols if col in with_idw.columns]
    with_idw[write_cols].to_csv(predictions_out, index=False)

    # Required final village-level output for operational consumption.
    latest_date = pd.to_datetime(with_idw["date"], errors="coerce").max()
    latest = with_idw[pd.to_datetime(with_idw["date"], errors="coerce") == latest_date].copy()
    latest_export = latest[["village_id", "predicted_groundwater", "has_piezometer", "confidence_score"]].copy()
    latest_export.to_csv(predictions_out.parent / "groundwater_predictions_latest.csv", index=False)

    metrics_df = pd.DataFrame([model_output.metrics])
    metrics_df["lag_leakage_rows"] = leakage_flag
    observed_eval = with_idw[pd.to_numeric(with_idw["groundwater_level"], errors="coerce").notna()].copy()
    if not observed_eval.empty:
        obs_y = pd.to_numeric(observed_eval["groundwater_level"], errors="coerce")
        obs_pred_xgb = pd.to_numeric(observed_eval["predicted_groundwater_xgb"], errors="coerce")
        obs_pred_idw = pd.to_numeric(observed_eval["predicted_groundwater_idw"], errors="coerce")
        xgb_rmse_obs = float(np.sqrt(np.mean((obs_y - obs_pred_xgb) ** 2)))
        idw_rmse_obs = float(np.sqrt(np.mean((obs_y - obs_pred_idw) ** 2)))
        metrics_df["observed_xgb_rmse"] = xgb_rmse_obs
        metrics_df["observed_idw_rmse"] = idw_rmse_obs
        metrics_df["model_wins_vs_idw_rmse_pct"] = (
            100.0 * (idw_rmse_obs - xgb_rmse_obs) / idw_rmse_obs if idw_rmse_obs > 0 else np.nan
        )
    metrics_df.to_csv(predictions_out.parent / "groundwater_model_metrics.csv", index=False)
    model_output.feature_importance.to_csv(predictions_out.parent / "feature_importance.csv", index=False)
    model_output.feature_importance.head(10).to_csv(predictions_out.parent / "feature_importance_top10.csv", index=False)

    validation = strict_spatial_temporal_validation(features, with_idw)
    if validation.empty:
        validation = pd.DataFrame(
            [{"split": "unavailable", "xgb_rmse": np.nan, "idw_rmse": np.nan, "xgb_rmse_improvement_pct_vs_idw": np.nan}]
        )
    validation.to_csv(predictions_out.parent / "validation_report.csv", index=False)
    comparison_table = validation[
        [col for col in ["split", "idw_rmse", "xgb_rmse", "xgb_rmse_improvement_pct_vs_idw"] if col in validation.columns]
    ].copy()
    comparison_table.to_csv(predictions_out.parent / "method_comparison.csv", index=False)

    robustness = build_robustness_reports(features, with_idw)
    robustness["ablation"].to_csv(predictions_out.parent / "ablation_study.csv", index=False)
    robustness["stress_test"].to_csv(predictions_out.parent / "stress_test_report.csv", index=False)
    robustness["confidence_validation"].to_csv(predictions_out.parent / "confidence_validation.csv", index=False)

    # Scatter payload for confidence-vs-error plotting in dashboard/notebook.
    conf_scatter = with_idw[
        [
            "village_id",
            "date",
            "has_piezometer",
            "confidence_score",
            "groundwater_level",
            "predicted_groundwater_xgb",
        ]
    ].copy()
    conf_scatter = conf_scatter[pd.to_numeric(conf_scatter["groundwater_level"], errors="coerce").notna()]
    conf_scatter["abs_error"] = np.abs(
        pd.to_numeric(conf_scatter["groundwater_level"], errors="coerce")
        - pd.to_numeric(conf_scatter["predicted_groundwater_xgb"], errors="coerce")
    )
    conf_scatter.to_csv(predictions_out.parent / "confidence_error_scatter.csv", index=False)

    # NEW: Generate GeoJSON for frontend direct consumption
    # We aggregate the full history for each village to enable the "Smart Hydrograph" in the UI
    history_agg = with_idw.sort_values("date").groupby("village_id").agg({
        "rainfall": list,
        "effective_recharge": list,
        "predicted_groundwater_xgb": list,
        "groundwater_level": list,
        "date": lambda x: [d.strftime("%Y-%m") for d in pd.to_datetime(x)]
    }).reset_index()

    history_agg = history_agg.rename(columns={
        "rainfall": "monthly_rainfall",
        "effective_recharge": "monthly_recharge",
        "predicted_groundwater_xgb": "monthly_predicted_gw",
        "groundwater_level": "monthly_actual_gw",
        "date": "monthly_dates"
    })

    latest_date = pd.to_datetime(with_idw["date"], errors="coerce").max()
    latest_preds = with_idw[pd.to_datetime(with_idw["date"], errors="coerce") == latest_date].copy()
    
    # Merge latest and history
    latest_with_history = latest_preds.merge(history_agg, on="village_id", how="left")
    
    # Merge predictions into village geometries
    villages_geo = mapped["villages"].to_crs("EPSG:4326").copy()
    map_data = villages_geo.merge(latest_with_history, on="village_id", how="left")
    
    # Add calculated diagnostic fields for frontend layers
    map_data["model_minus_idw_latest"] = map_data["predicted_groundwater_xgb"] - map_data["predicted_groundwater_idw"]
    map_data["abs_error_latest"] = np.abs(map_data["groundwater_level"] - map_data["predicted_groundwater_xgb"])
    map_data["has_observation_latest"] = map_data["groundwater_level"].notna().astype(int)
    
    # Convert lists to JSON strings for GeoJSON compatibility
    # Ensure NaNs are converted to None so json.dumps produces valid nulls
    for col in ["monthly_rainfall", "monthly_recharge", "monthly_predicted_gw", "monthly_actual_gw", "monthly_dates"]:
        map_data[col] = map_data[col].apply(lambda x: json.dumps([None if isinstance(i, float) and np.isnan(i) else i for i in x]) if isinstance(x, list) else x)

    geojson_path = predictions_out.parent / "map_data_predictions.geojson"
    # Canonical schema normalization to keep downstream UI/API fields consistent.
    map_data = normalize_prediction_dataframe(map_data)
    validate_schema_dataframe(map_data)
    map_data.to_file(geojson_path, driver="GeoJSON")

    # NEW: Generate Judge Summary
    judge_summary = build_judge_summary(validation, robustness, model_output.feature_importance)
    judge_path = predictions_out.parent / "judge_summary.json"
    with open(judge_path, "w") as f:
        json.dump(judge_summary, f, indent=2)

    # RUN CONTRACT: metadata.json
    import uuid
    metadata = {
        "run_id": str(uuid.uuid4()),
        "data_version": "v1.0",
        "model_version": "stgnn_xgb_v2",
        "features_used": list(model_output.feature_importance["feature"]) if not model_output.feature_importance.empty else [],
        "train_regions": list(mapped["villages"]["district"].dropna().unique()) if "district" in mapped["villages"].columns else [],
        "test_regions": ["temporal_holdout_2024", "spatial_kfold"],
        "rmse": float(validation[validation["split"] == "temporal_holdout_strict"]["xgb_rmse"].iloc[0]) if not validation[validation["split"] == "temporal_holdout_strict"].empty else 0.0,
        "mae": float(validation[validation["split"] == "temporal_holdout_strict"]["xgb_mae"].iloc[0]) if not validation[validation["split"] == "temporal_holdout_strict"].empty else 0.0
    }
    metadata_path = predictions_out.parent / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # REGISTER MODEL
    try:
        from ml_pipeline.registry.registry import ModelRegistry
        registry = ModelRegistry(str(predictions_out.parent.parent / "models" / "registry.json"))
        registry.register_model(
            model_name="groundwater_hybrid_v1",
            version=metadata["model_version"],
            metrics={"rmse": metadata["rmse"], "mae": metadata["mae"]},
            artifacts={"metadata": str(metadata_path)}
        )
    except Exception as e:
        print(f"Registry warning: {e}")


    build_map(
        villages=mapped["villages"],  # type: ignore[arg-type]
        predictions=with_idw,
        piezometer_village=mapped["piezometer_village"],  # type: ignore[arg-type]
        streams=loaded.streams,
        canals=loaded.canals,
        tanks=loaded.tanks,
        out_html=map_out,
    )

    # Sync to frontend
    frontend_data_dir = Path("frontend/public/data")
    if frontend_data_dir.exists():
        print(f"Syncing data to {frontend_data_dir}...")
        for f in [geojson_path, judge_path]:
            if f.exists():
                shutil.copy(f, frontend_data_dir / f.name)

    print(f"Saved predictions: {predictions_out}")
    print(f"Saved latest village predictions: {predictions_out.parent / 'groundwater_predictions_latest.csv'}")
    print(f"Saved map: {map_out}")
    print(f"Saved metrics: {predictions_out.parent / 'groundwater_model_metrics.csv'}")
    print(f"Saved validation report: {predictions_out.parent / 'validation_report.csv'}")
    print(f"Saved judge summary: {judge_path}")
    print(f"Saved GeoJSON for dashboard: {geojson_path}")


if __name__ == "__main__":
    args = parse_args()
    run(raw_dir=args.raw_dir, predictions_out=args.predictions_out, map_out=args.map_out)
