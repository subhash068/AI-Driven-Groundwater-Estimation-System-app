from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from groundwater_pipeline.data.loaders import load_all_data
from groundwater_pipeline.processing.spatial_mapping import build_mapped_tables
from groundwater_pipeline.processing.feature_engineering import build_monthly_features
from groundwater_pipeline.models.xgboost_model import train_and_predict_xgboost
from groundwater_pipeline.models.idw import add_idw_baseline
from groundwater_pipeline.models.validation import strict_spatial_temporal_validation, build_robustness_reports, build_judge_summary
from groundwater_pipeline.visualization.map_view import build_map
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
    latest_date = pd.to_datetime(with_idw["date"], errors="coerce").max()
    latest_preds = with_idw[pd.to_datetime(with_idw["date"], errors="coerce") == latest_date].copy()
    
    # Merge predictions into village geometries
    villages_geo = mapped["villages"].to_crs("EPSG:4326").copy()
    map_data = villages_geo.merge(latest_preds, on="village_id", how="left")
    
    # Add calculated diagnostic fields for frontend layers
    map_data["model_minus_idw_latest"] = map_data["predicted_groundwater_xgb"] - map_data["predicted_groundwater_idw"]
    map_data["abs_error_latest"] = np.abs(map_data["groundwater_level"] - map_data["predicted_groundwater_xgb"])
    map_data["has_observation_latest"] = map_data["groundwater_level"].notna().astype(int)
    
    geojson_path = predictions_out.parent / "map_data_predictions.geojson"
    map_data.to_file(geojson_path, driver="GeoJSON")

    # NEW: Generate Judge Summary
    judge_summary = build_judge_summary(validation, robustness, model_output.feature_importance)
    judge_path = predictions_out.parent / "judge_summary.json"
    with open(judge_path, "w") as f:
        json.dump(judge_summary, f, indent=2)

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
