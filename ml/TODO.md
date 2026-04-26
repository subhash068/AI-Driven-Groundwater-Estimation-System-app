# XGBoost Upgrade TODO

Approved: replace the earlier RandomForest regressor with `XGBRegressor` in `ml/interpolation_engine.py`.

## Status

- [x] TODO created
- [x] `ml/interpolation_engine.py` updated to use `XGBRegressor`
- [x] `xgboost` added to `requirements.txt`
- [x] Confidence scoring updated for XGBoost compatibility
- [ ] Install dependencies with `pip install -r requirements.txt`
- [ ] Test `python ml/interpolation_engine.py --input data.geojson --out test.geojson`
- [ ] Compare metrics against prior model output

## Note

`XGBRegressor` does not expose RandomForest-style `estimators_`, so confidence scoring now uses distance from the training feature distribution instead of per-tree spread.
