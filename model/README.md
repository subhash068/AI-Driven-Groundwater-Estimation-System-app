# Groundwater AI Model Pipeline

This folder hosts the production-oriented training and interpolation pipeline used by backend prediction workflows.

## Quick run

1. Stage raw files:
   `python -m model.stage_data`
2. Train + export map data:
   `python -m model.pipeline --kriging-strategy residual`

Outputs:
- `data/processed/village_features.parquet`
- `data/exports/map_data.geojson`
- `data/exports/lulc_trends.csv`
- `model/artifacts/model_xgb.json`
- `model/artifacts/metrics.json`

## Sparsity Experiment

Run the piezometer sparsity evaluation:
`python -m model.sparsity_experiment --dataset output/final_dataset.csv --data-dir data/raw --sample-pcts 10 20 30 --repeats 10`

Outputs:
- `data/exports/sparsity_experiment/sparsity_experiment_raw.csv`
- `data/exports/sparsity_experiment/sparsity_experiment_summary.csv`
- `data/exports/sparsity_experiment/accuracy_vs_sparsity.svg`

