from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd

AREA_CRS = "EPSG:32644"


def idw_predict_for_month(
    villages: gpd.GeoDataFrame,
    piezo_with_village: pd.DataFrame,
    target_month: pd.Timestamp,
    power: float = 2.0,
) -> pd.DataFrame:
    obs = piezo_with_village[pd.to_datetime(piezo_with_village["month"]) == pd.Timestamp(target_month)].copy()
    if obs.empty:
        return pd.DataFrame({"village_id": villages["village_id"], "predicted_groundwater_idw": np.nan})

    village_centroids = villages.to_crs(AREA_CRS).copy()
    village_centroids["geometry"] = village_centroids.geometry.centroid
    village_centroids = village_centroids.to_crs("EPSG:4326")
    village_centroids["x"] = village_centroids.geometry.x
    village_centroids["y"] = village_centroids.geometry.y

    obs_xy = obs[["lon", "lat", "groundwater_level"]].dropna().to_numpy(dtype=float)
    if len(obs_xy) == 0:
        return pd.DataFrame({"village_id": villages["village_id"], "predicted_groundwater_idw": np.nan})

    preds = []
    for _, row in village_centroids.iterrows():
        dx = obs_xy[:, 0] - float(row["x"])
        dy = obs_xy[:, 1] - float(row["y"])
        dist = np.sqrt(dx * dx + dy * dy)
        dist = np.where(dist == 0.0, 1e-8, dist)
        weights = 1.0 / np.power(dist, power)
        pred = float(np.sum(weights * obs_xy[:, 2]) / np.sum(weights))
        preds.append(pred)

    return pd.DataFrame(
        {"village_id": village_centroids["village_id"].astype(int), "predicted_groundwater_idw": preds}
    )


def add_idw_baseline(
    village_month_predictions: pd.DataFrame,
    villages: gpd.GeoDataFrame,
    piezo_with_village: pd.DataFrame,
) -> pd.DataFrame:
    frame = village_month_predictions.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.to_period("M").dt.to_timestamp()
    all_months = sorted(frame["date"].dropna().unique())

    idw_frames = []
    for month in all_months:
        idw_month = idw_predict_for_month(villages, piezo_with_village, pd.Timestamp(month))
        idw_month["date"] = pd.Timestamp(month)
        idw_frames.append(idw_month)

    if not idw_frames:
        frame["predicted_groundwater_idw"] = np.nan
        return frame

    idw_all = pd.concat(idw_frames, ignore_index=True)
    out = frame.merge(idw_all, on=["village_id", "date"], how="left")
    return out
