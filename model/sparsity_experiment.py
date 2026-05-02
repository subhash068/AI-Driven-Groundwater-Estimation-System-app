import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from ml_pipeline.data.generate_dataset import load_villages
from model.config import AREA_CRS, DEFAULT_CRS
from model.pipeline import OrdinaryKriging
from model.train_from_csv import _prepare_training_frame


def _load_village_geometries(data_dir: Path) -> gpd.GeoDataFrame:
    village_zip = data_dir / "Village_Mandal_DEM_Soils_MITanks_Krishna.zip"
    if village_zip.exists():
        villages = load_villages(village_zip)
        return villages[["Village_ID", "Village_Name", "geometry"]].copy()

    fallback = Path("frontend/public/data/villages.geojson")
    villages = gpd.read_file(fallback)
    villages = villages.rename(columns={c: str(c).strip() for c in villages.columns})
    name_col = next((c for c in villages.columns if str(c).strip().lower() in {"village_name", "dvname", "village"}), None)
    villages["Village_Name"] = villages[name_col].astype(str).str.strip() if name_col else np.arange(1, len(villages) + 1).astype(str)
    villages["Village_ID"] = np.arange(1, len(villages) + 1, dtype=int)
    if villages.crs is None:
        villages = villages.set_crs(DEFAULT_CRS)
    return villages[["Village_ID", "Village_Name", "geometry"]].to_crs(DEFAULT_CRS)


def _ground_truth_mask(df: pd.DataFrame) -> pd.Series:
    if "obs_station_count" in df.columns:
        obs = pd.to_numeric(df["obs_station_count"], errors="coerce").fillna(0.0)
        return obs > 0
    if "monthly_depths" in df.columns:
        monthly = df["monthly_depths"].fillna("[]").astype(str).str.strip()
        return monthly != "[]"
    return pd.to_numeric(df["GW_Level"], errors="coerce").notna()


def _train_xgb(X_train: pd.DataFrame, y_train: pd.Series) -> xgb.XGBRegressor:
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
    return model


def _idw_residual_correction(
    train_coords: np.ndarray,
    train_residuals: np.ndarray,
    query_coords: np.ndarray,
    power: float = 2.0,
    neighbor_k: int = 8,
) -> np.ndarray:
    corrections = np.zeros(len(query_coords), dtype=float)
    if len(train_coords) == 0:
        return corrections

    for i, query in enumerate(query_coords):
        distances = np.linalg.norm(train_coords - query, axis=1)
        if np.any(distances == 0):
            corrections[i] = float(train_residuals[np.argmin(distances)])
            continue
        order = np.argsort(distances)[: min(neighbor_k, len(distances))]
        local_distances = distances[order]
        weights = 1.0 / np.power(local_distances, power)
        corrections[i] = float(np.dot(weights, train_residuals[order]) / weights.sum())
    return corrections


def _spatially_smoothed_predictions(
    train_coords: np.ndarray,
    train_truth: np.ndarray,
    train_xgb_pred: np.ndarray,
    test_coords: np.ndarray,
    test_xgb_pred: np.ndarray,
) -> np.ndarray:
    residuals = train_truth - train_xgb_pred
    if len(train_coords) < 3:
        return test_xgb_pred

    if OrdinaryKriging is not None:
        try:
            ok = OrdinaryKriging(
                train_coords[:, 0],
                train_coords[:, 1],
                residuals,
                variogram_model="spherical",
                verbose=False,
                enable_plotting=False,
            )
            corrections, _ = ok.execute("points", test_coords[:, 0], test_coords[:, 1])
            return test_xgb_pred + np.asarray(corrections, dtype=float)
        except Exception:
            pass

    corrections = _idw_residual_correction(train_coords, residuals, test_coords)
    return test_xgb_pred + corrections


def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _format_metric(value: float) -> str:
    return f"{value:.3f}" if math.isfinite(value) else "nan"


def _svg_line(points: list[tuple[float, float]], color: str) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _build_accuracy_plot(summary_df: pd.DataFrame, output_path: Path) -> None:
    metrics = [
        ("rmse", "RMSE"),
        ("mae", "MAE"),
        ("r2", "R²"),
    ]
    models = [
        ("xgboost", "#1f77b4"),
        ("xgboost_spatial_smoothing", "#d62728"),
    ]
    sparsities = sorted(summary_df["sample_pct"].unique())
    if not sparsities:
        return

    width = 1080
    height = 420
    margin = 55
    panel_gap = 30
    panel_width = (width - (margin * 2) - (panel_gap * 2)) / 3
    panel_height = height - 110
    plot_top = 40

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fafaf8"/>',
        '<text x="40" y="28" font-family="Arial" font-size="20" font-weight="700" fill="#1f2937">Accuracy vs Sparsity</text>',
        '<text x="40" y="48" font-family="Arial" font-size="12" fill="#4b5563">Ground truth villages with observations; lower RMSE/MAE and higher R² are better.</text>',
    ]

    for panel_idx, (metric_key, metric_label) in enumerate(metrics):
        panel_left = margin + panel_idx * (panel_width + panel_gap)
        panel_right = panel_left + panel_width
        panel_bottom = plot_top + panel_height

        metric_values = summary_df[metric_key].to_numpy(dtype=float)
        metric_min = float(np.nanmin(metric_values))
        metric_max = float(np.nanmax(metric_values))
        if not math.isfinite(metric_min) or not math.isfinite(metric_max) or math.isclose(metric_min, metric_max):
            metric_min -= 1.0
            metric_max += 1.0

        svg_parts.append(f'<rect x="{panel_left:.2f}" y="{plot_top:.2f}" width="{panel_width:.2f}" height="{panel_height:.2f}" fill="white" stroke="#d1d5db"/>')
        svg_parts.append(f'<text x="{panel_left + 8:.2f}" y="{plot_top + 18:.2f}" font-family="Arial" font-size="14" font-weight="700" fill="#111827">{metric_label}</text>')
        svg_parts.append(f'<line x1="{panel_left:.2f}" y1="{panel_bottom:.2f}" x2="{panel_right:.2f}" y2="{panel_bottom:.2f}" stroke="#9ca3af"/>')
        svg_parts.append(f'<line x1="{panel_left:.2f}" y1="{plot_top:.2f}" x2="{panel_left:.2f}" y2="{panel_bottom:.2f}" stroke="#9ca3af"/>')

        def x_pos(sample_pct: float) -> float:
            if len(sparsities) == 1:
                return panel_left + panel_width / 2
            return panel_left + ((sample_pct - sparsities[0]) / (sparsities[-1] - sparsities[0])) * (panel_width - 30) + 15

        def y_pos(metric_value: float) -> float:
            scaled = (metric_value - metric_min) / (metric_max - metric_min)
            return panel_bottom - scaled * (panel_height - 35) - 15

        for sample_pct in sparsities:
            xpos = x_pos(sample_pct)
            svg_parts.append(f'<line x1="{xpos:.2f}" y1="{panel_bottom:.2f}" x2="{xpos:.2f}" y2="{panel_bottom + 4:.2f}" stroke="#6b7280"/>')
            svg_parts.append(f'<text x="{xpos:.2f}" y="{panel_bottom + 18:.2f}" text-anchor="middle" font-family="Arial" font-size="11" fill="#374151">{int(sample_pct)}%</text>')

        for model_name, color in models:
            model_df = summary_df[summary_df["model"] == model_name].sort_values("sample_pct")
            points = [(x_pos(float(row["sample_pct"])), y_pos(float(row[metric_key]))) for _, row in model_df.iterrows()]
            if not points:
                continue
            svg_parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{_svg_line(points, color)}"/>')
            for (x, y), (_, row) in zip(points, model_df.iterrows()):
                svg_parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}"/>')
                svg_parts.append(
                    f'<text x="{x:.2f}" y="{y - 8:.2f}" text-anchor="middle" font-family="Arial" font-size="10" fill="{color}">{_format_metric(float(row[metric_key]))}</text>'
                )

    legend_y = height - 30
    svg_parts.extend(
        [
            '<line x1="40" y1="390" x2="70" y2="390" stroke="#1f77b4" stroke-width="3"/>',
            '<text x="78" y="394" font-family="Arial" font-size="12" fill="#111827">XGBoost</text>',
            '<line x1="180" y1="390" x2="210" y2="390" stroke="#d62728" stroke-width="3"/>',
            '<text x="218" y="394" font-family="Arial" font-size="12" fill="#111827">XGBoost + spatial smoothing</text>',
            f'<text x="{width - 210}" y="{legend_y}" font-family="Arial" font-size="12" fill="#4b5563">Observed piezometer fraction</text>',
            '</svg>',
        ]
    )

    output_path.write_text("\n".join(svg_parts), encoding="utf-8")


def run_experiment(
    dataset_csv: Path,
    data_dir: Path,
    output_dir: Path,
    sample_pcts: list[int],
    repeats: int,
    seed: int,
) -> dict[str, object]:
    df = pd.read_csv(dataset_csv)
    truth_mask = _ground_truth_mask(df)
    ground_truth_df = df[truth_mask].copy()
    if len(ground_truth_df) < 10:
        raise ValueError("Not enough observed villages for sparsity experiment")

    model_df, feature_cols = _prepare_training_frame(df)
    model_df["Village_ID"] = pd.to_numeric(df["Village_ID"], errors="coerce")
    model_df["Village_Name"] = df["Village_Name"].astype(str)

    villages = _load_village_geometries(data_dir)
    villages["Village_ID"] = pd.to_numeric(villages["Village_ID"], errors="coerce").astype(int)
    villages_area = villages.to_crs(villages.estimate_utm_crs() or AREA_CRS).copy()
    villages_area["centroid"] = villages_area.geometry.centroid
    villages_area["coord_x"] = villages_area["centroid"].x
    villages_area["coord_y"] = villages_area["centroid"].y

    evaluation_df = (
        ground_truth_df[["Village_ID", "Village_Name", "GW_Level"]]
        .merge(model_df[["Village_ID", "Village_Name", "GW_Level", *feature_cols]], on=["Village_ID", "Village_Name", "GW_Level"], how="inner")
        .merge(villages_area[["Village_ID", "coord_x", "coord_y"]], on="Village_ID", how="inner")
    )
    evaluation_df["GW_Level"] = pd.to_numeric(evaluation_df["GW_Level"], errors="coerce")
    evaluation_df = evaluation_df.dropna(subset=["GW_Level", "coord_x", "coord_y"]).copy()
    if len(evaluation_df) < 10:
        raise ValueError("Evaluation dataset is too small after merging coordinates and ground truth")

    output_dir.mkdir(parents=True, exist_ok=True)

    raw_rows: list[dict[str, object]] = []
    rng = np.random.default_rng(seed)

    for sample_pct in sample_pcts:
        sample_fraction = sample_pct / 100.0
        for repeat in range(repeats):
            sample_size = max(3, int(round(len(evaluation_df) * sample_fraction)))
            sample_size = min(sample_size, len(evaluation_df) - 1)
            chosen = rng.choice(evaluation_df.index.to_numpy(), size=sample_size, replace=False)
            train_df = evaluation_df.loc[np.sort(chosen)].copy()
            test_df = evaluation_df.drop(index=chosen).copy()
            if test_df.empty:
                continue

            X_train = train_df[feature_cols]
            y_train = train_df["GW_Level"]
            X_test = test_df[feature_cols]
            y_test = test_df["GW_Level"]

            model = _train_xgb(X_train, y_train)
            train_xgb_pred = model.predict(X_train)
            test_xgb_pred = model.predict(X_test)

            train_coords = train_df[["coord_x", "coord_y"]].to_numpy(dtype=float)
            test_coords = test_df[["coord_x", "coord_y"]].to_numpy(dtype=float)
            test_smooth_pred = _spatially_smoothed_predictions(
                train_coords=train_coords,
                train_truth=y_train.to_numpy(dtype=float),
                train_xgb_pred=np.asarray(train_xgb_pred, dtype=float),
                test_coords=test_coords,
                test_xgb_pred=np.asarray(test_xgb_pred, dtype=float),
            )

            for model_name, y_pred in (
                ("xgboost", np.asarray(test_xgb_pred, dtype=float)),
                ("xgboost_spatial_smoothing", np.asarray(test_smooth_pred, dtype=float)),
            ):
                metrics = _compute_metrics(y_test.to_numpy(dtype=float), y_pred)
                raw_rows.append(
                    {
                        "sample_pct": sample_pct,
                        "repeat": repeat,
                        "train_size": len(train_df),
                        "test_size": len(test_df),
                        "model": model_name,
                        **metrics,
                    }
                )

    raw_df = pd.DataFrame(raw_rows).sort_values(["sample_pct", "repeat", "model"]).reset_index(drop=True)
    summary_df = (
        raw_df.groupby(["sample_pct", "model"], as_index=False)[["rmse", "mae", "r2"]]
        .mean()
        .sort_values(["sample_pct", "model"])
        .reset_index(drop=True)
    )

    raw_path = output_dir / "sparsity_experiment_raw.csv"
    summary_path = output_dir / "sparsity_experiment_summary.csv"
    plot_path = output_dir / "accuracy_vs_sparsity.svg"
    report_path = output_dir / "sparsity_experiment_report.json"

    raw_df.to_csv(raw_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    _build_accuracy_plot(summary_df, plot_path)

    result = {
        "dataset": str(dataset_csv),
        "ground_truth_villages": int(len(evaluation_df)),
        "sample_pcts": sample_pcts,
        "repeats": repeats,
        "seed": seed,
        "outputs": {
            "raw_metrics_csv": str(raw_path),
            "summary_metrics_csv": str(summary_path),
            "plot_svg": str(plot_path),
        },
        "summary": summary_df.to_dict(orient="records"),
    }
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run groundwater sparsity evaluation for village predictions")
    parser.add_argument("--dataset", type=Path, default=Path("output/final_dataset.csv"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/exports/sparsity_experiment"))
    parser.add_argument("--sample-pcts", nargs="+", type=int, default=[10, 20, 30])
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_experiment(
        dataset_csv=args.dataset,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        sample_pcts=args.sample_pcts,
        repeats=args.repeats,
        seed=args.seed,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
