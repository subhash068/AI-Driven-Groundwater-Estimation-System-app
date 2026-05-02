from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd

AREA_CRS = "EPSG:32644"


def _distance_to_layer_km(villages: gpd.GeoDataFrame, layer: gpd.GeoDataFrame, col_name: str) -> pd.DataFrame:
    v = villages[["village_id", "geometry"]].to_crs(AREA_CRS).copy()
    v["geometry"] = v.geometry.centroid
    if layer is None or layer.empty:
        return pd.DataFrame({"village_id": v["village_id"], col_name: np.nan})

    l = layer.to_crs(AREA_CRS).copy()
    nearest = gpd.sjoin_nearest(v, l[["geometry"]], how="left", distance_col="distance_m")
    out = nearest[["village_id", "distance_m"]].drop_duplicates("village_id").copy()
    out[col_name] = pd.to_numeric(out["distance_m"], errors="coerce") / 1000.0
    return out[["village_id", col_name]]


def _calculate_infiltration_factor(df: pd.DataFrame) -> pd.Series:
    """Estimates infiltration factor based on LULC and Aquifer type."""
    # LULC Base Factors
    lulc_factors = {
        "Crops": 0.15,
        "Trees": 0.20,
        "Bare Ground": 0.12,
        "Rangeland": 0.18,
        "Built Area": 0.05,
        "Water": 0.30,
        "Unknown": 0.12,
    }

    def get_factor(row):
        lulc = str(row.get("lulc_class", "Unknown"))
        aquifer = str(row.get("aquifer_type", "Unknown")).lower()
        base_f = lulc_factors.get(lulc, 0.12)
        geo_mult = 1.0
        if any(x in aquifer for x in ["alluvium", "sand", "unconsolidated"]):
            geo_mult = 1.5
        elif any(x in aquifer for x in ["hard rock", "basalt", "granite", "shale"]):
            geo_mult = 0.7
        return base_f * geo_mult

    return df.apply(get_factor, axis=1)


def _monthly_groundwater_and_lags(piezo_village: pd.DataFrame) -> pd.DataFrame:
    monthly = (
        piezo_village.groupby(["village_id", "month"], as_index=False)["groundwater_level"]
        .mean()
        .rename(columns={"month": "date"})
    )
    monthly = monthly.sort_values(["village_id", "date"]).reset_index(drop=True)
    for lag in [1, 2, 3]:
        monthly[f"gw_lag_{lag}"] = monthly.groupby("village_id")["groundwater_level"].shift(lag)
    return monthly


def _build_spatial_groundwater_features(
    villages: gpd.GeoDataFrame,
    month_index: pd.DataFrame,
    gw_monthly: pd.DataFrame,
    radius_km: float = 10.0,
    idw_power: float = 2.0,
) -> pd.DataFrame:
    villages_area = villages[["village_id", "geometry"]].to_crs(AREA_CRS).copy()
    villages_area["geometry"] = villages_area.geometry.centroid
    villages_area = villages_area.sort_values("village_id").reset_index(drop=True)
    coords = np.column_stack([villages_area.geometry.x.to_numpy(), villages_area.geometry.y.to_numpy()])
    village_ids = villages_area["village_id"].to_numpy(dtype=int)
    village_pos = {vid: idx for idx, vid in enumerate(village_ids)}

    # Pairwise distances (km) are reused across months.
    dist_km = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2) / 1000.0
    radius_mask = dist_km <= radius_km

    observed = gw_monthly[["village_id", "date", "groundwater_level"]].copy()
    observed["date"] = pd.to_datetime(observed["date"]).dt.to_period("M").dt.to_timestamp()
    observed["groundwater_level"] = pd.to_numeric(observed["groundwater_level"], errors="coerce")
    observed = observed.dropna(subset=["village_id", "date", "groundwater_level"])
    observed["village_id"] = observed["village_id"].astype(int)

    out_rows: list[dict[str, float | int | pd.Timestamp]] = []
    for date in pd.to_datetime(month_index["date"]).dt.to_period("M").dt.to_timestamp().sort_values().unique():
        month_obs = observed[observed["date"] == pd.Timestamp(date)]
        obs_map = month_obs.groupby("village_id", as_index=True)["groundwater_level"].mean().to_dict()
        obs_ids = np.array([vid for vid in obs_map.keys() if vid in village_pos], dtype=int)
        obs_values = np.array([obs_map[vid] for vid in obs_ids], dtype=float) if len(obs_ids) else np.array([], dtype=float)
        obs_positions = np.array([village_pos[vid] for vid in obs_ids], dtype=int) if len(obs_ids) else np.array([], dtype=int)

        for vid in village_ids:
            idx = village_pos[int(vid)]
            # Exclude self-observation from spatial predictors to avoid target leakage.
            if len(obs_ids):
                local_obs_ids = obs_ids[obs_ids != vid]
                local_obs_vals = np.array([obs_map[o] for o in local_obs_ids], dtype=float)
                local_obs_pos = np.array([village_pos[o] for o in local_obs_ids], dtype=int)
            else:
                local_obs_ids = np.array([], dtype=int)
                local_obs_vals = np.array([], dtype=float)
                local_obs_pos = np.array([], dtype=int)

            if len(local_obs_ids) == 0:
                nearest_distance = np.nan
                nearest_value = np.nan
                avg_within = np.nan
                idw_weighted = np.nan
                nearby_std = np.nan
                nearby_count = 0
            else:
                d = dist_km[idx, local_obs_pos]
                nearest_i = int(np.argmin(d))
                nearest_distance = float(d[nearest_i])
                nearest_value = float(local_obs_vals[nearest_i])

                nearby_mask = d <= radius_km
                nearby_count = int(np.sum(nearby_mask))
                avg_within = float(np.mean(local_obs_vals[nearby_mask])) if nearby_count > 0 else np.nan
                nearby_std = float(np.std(local_obs_vals[nearby_mask])) if nearby_count > 1 else np.nan

                safe_d = np.where(d <= 1e-9, 1e-9, d)
                weights = 1.0 / np.power(safe_d, idw_power)
                idw_weighted = float(np.sum(weights * local_obs_vals) / np.sum(weights))

            out_rows.append(
                {
                    "village_id": int(vid),
                    "date": pd.Timestamp(date),
                    "nearest_piezometer_distance_km": nearest_distance,
                    "nearest_piezometer_groundwater": nearest_value,
                    "average_groundwater_within_10km": avg_within,
                    "weighted_groundwater_idw": idw_weighted,
                    "nearby_groundwater_std_10km": nearby_std,
                    "nearby_piezometer_count_10km": nearby_count,
                }
            )

    return pd.DataFrame(out_rows)


def build_monthly_features(
    villages: gpd.GeoDataFrame,
    mapped: dict[str, pd.DataFrame | gpd.GeoDataFrame],
    canals: gpd.GeoDataFrame,
    streams: gpd.GeoDataFrame,
    tanks: gpd.GeoDataFrame,
    pumping: pd.DataFrame,
) -> pd.DataFrame:
    piezo = mapped["piezometer_village"]  # type: ignore[index]
    rain = mapped["rainfall_village"]  # type: ignore[index]
    aquifer = mapped["aquifer_village"]  # type: ignore[index]
    lulc = mapped["lulc_village"]  # type: ignore[index]

    gw_monthly = _monthly_groundwater_and_lags(piezo)  # observed villages and months
    rain = rain.rename(columns={"rainfall_mm": "rainfall"}).copy()
    rain["date"] = pd.to_datetime(rain["date"])

    # Build full village x month frame using rainfall coverage.
    month_index = rain[["date"]].drop_duplicates().sort_values("date")
    v = villages[["village_id"]].copy()
    grid = v.assign(_k=1).merge(month_index.assign(_k=1), on="_k").drop(columns="_k")

    features = grid.merge(rain, on=["village_id", "date"], how="left")
    features = features.merge(gw_monthly, on=["village_id", "date"], how="left")
    features = features.merge(aquifer, on="village_id", how="left")
    features = features.merge(lulc, on="village_id", how="left")

    # Distances to hydro features.
    for layer, out_col in [
        (canals, "distance_to_canal_km"),
        (streams, "distance_to_stream_km"),
        (tanks, "distance_to_tank_km"),
    ]:
        dist = _distance_to_layer_km(villages, layer, out_col)
        features = features.merge(dist, on="village_id", how="left")

    has_piezometer = (
        piezo[["village_id"]]
        .dropna()
        .drop_duplicates()
        .assign(has_piezometer=1)
    )
    features = features.merge(has_piezometer, on="village_id", how="left")
    features["has_piezometer"] = features["has_piezometer"].fillna(0).astype(int)

    spatial = _build_spatial_groundwater_features(villages=villages, month_index=month_index, gw_monthly=gw_monthly)
    features = features.merge(spatial, on=["village_id", "date"], how="left")

    village_centroids = villages[["village_id", "geometry"]].to_crs(AREA_CRS).copy()
    village_centroids["geometry"] = village_centroids.geometry.centroid
    village_centroids["village_x"] = village_centroids.geometry.x
    village_centroids["village_y"] = village_centroids.geometry.y
    features = features.merge(village_centroids[["village_id", "village_x", "village_y"]], on="village_id", how="left")

    features = features.merge(pumping.rename(columns={"pumping": "pumping_data"}), on="village_id", how="left")

    # Encode categorical features.
    for col in ["aquifer_type", "lulc_class"]:
        features[col] = features[col].fillna("Unknown").astype(str)
        features[f"{col}_enc"] = features[col].astype("category").cat.codes

    # Fill independent numeric predictors.
    features["rainfall"] = pd.to_numeric(features["rainfall"], errors="coerce").fillna(0.0)
    for col in [
        "distance_to_canal_km",
        "distance_to_stream_km",
        "distance_to_tank_km",
        "pumping_data",
        "nearest_piezometer_distance_km",
        "nearest_piezometer_groundwater",
        "average_groundwater_within_10km",
        "weighted_groundwater_idw",
        "nearby_groundwater_std_10km",
    ]:
        features[col] = pd.to_numeric(features[col], errors="coerce")
        features[col] = features[col].fillna(features[col].median())
    features["nearby_piezometer_count_10km"] = (
        pd.to_numeric(features["nearby_piezometer_count_10km"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    # Recompute lags from the full village-month frame to guarantee strict t-1/t-2/t-3 semantics.
    features["groundwater_level"] = pd.to_numeric(features["groundwater_level"], errors="coerce")
    for lag in [1, 2, 3]:
        lag_col = f"gw_lag_{lag}"
        features[lag_col] = features.groupby("village_id")["groundwater_level"].shift(lag)
        features[lag_col] = features[lag_col].fillna(0.0)
    features["lag_availability"] = features[["gw_lag_1", "gw_lag_2", "gw_lag_3"]].notna().mean(axis=1)

    # Rainfall recharge features from historical-only windows (shift(1) prevents future leakage).
    features = features.sort_values(["village_id", "date"]).reset_index(drop=True)
    rainfall_hist = features.groupby("village_id")["rainfall"].shift(1)
    
    # Lag features as requested (1m, 3m, 6m)
    features["rainfall_lag_1m"] = rainfall_hist
    features["rainfall_lag_3m"] = (
        rainfall_hist.groupby(features["village_id"]).rolling(3, min_periods=1).mean().reset_index(level=0, drop=True)
    )
    features["rainfall_lag_6m"] = (
        rainfall_hist.groupby(features["village_id"]).rolling(6, min_periods=1).mean().reset_index(level=0, drop=True)
    )
    
    features["rainfall_3m_sum"] = (
        rainfall_hist.groupby(features["village_id"]).rolling(3, min_periods=1).sum().reset_index(level=0, drop=True)
    )
    features["rainfall_6m_sum"] = (
        rainfall_hist.groupby(features["village_id"]).rolling(6, min_periods=1).sum().reset_index(level=0, drop=True)
    )
    rain_12m_mean = (
        rainfall_hist.groupby(features["village_id"]).rolling(12, min_periods=3).mean().reset_index(level=0, drop=True)
    )
    features["rainfall_anomaly"] = features["rainfall"] - rain_12m_mean
    
    # Calculate effective recharge
    features["infiltration_factor"] = _calculate_infiltration_factor(features)
    features["effective_recharge"] = features["rainfall"] * features["infiltration_factor"]

    # Seasonal Phases
    def get_season(month):
        if 6 <= month <= 9:
            return "Monsoon"
        elif 10 <= month <= 12:
            return "Post-monsoon"
        else:
            return "Pre-monsoon"

    features["seasonal_phase"] = features["date"].dt.month.apply(get_season)
    features["seasonal_phase_enc"] = features["seasonal_phase"].astype("category").cat.codes

    for col in ["rainfall_3m_sum", "rainfall_6m_sum", "rainfall_anomaly", "rainfall_lag_1m", "rainfall_lag_3m", "rainfall_lag_6m", "effective_recharge"]:
        features[col] = pd.to_numeric(features[col], errors="coerce").fillna(0.0)

    features["month"] = pd.to_datetime(features["date"]).dt.to_period("M").astype(str)
    return features
