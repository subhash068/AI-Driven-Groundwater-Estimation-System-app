from __future__ import annotations

from pathlib import Path
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import folium
from folium.plugins import TimestampedGeoJson


def _style_fn(feature: dict) -> dict:
    value = feature["properties"].get("predicted_groundwater_xgb_latest")
    confidence = feature["properties"].get("confidence_score_latest")
    confidence = 0.25 if confidence is None else float(np.clip(confidence, 0.0, 1.0))
    if value is None:
        return {"fillColor": "#d1d5db", "color": "#6b7280", "weight": 1, "fillOpacity": 0.15 + 0.55 * confidence}
    if value >= 12:
        color = "#b91c1c"
    elif value >= 8:
        color = "#f59e0b"
    else:
        color = "#16a34a"
    return {"fillColor": color, "color": "#1f2937", "weight": 1, "fillOpacity": 0.20 + 0.70 * confidence}


def _style_fn_idw(feature: dict) -> dict:
    value = feature["properties"].get("predicted_groundwater_idw_latest")
    if value is None:
        return {"fillColor": "#d1d5db", "color": "#6b7280", "weight": 1, "fillOpacity": 0.45}
    if value >= 12:
        color = "#7f1d1d"
    elif value >= 8:
        color = "#b45309"
    else:
        color = "#166534"
    return {"fillColor": color, "color": "#111827", "weight": 1, "fillOpacity": 0.55}


def _style_fn_model_minus_idw(feature: dict) -> dict:
    delta = feature["properties"].get("model_minus_idw_latest")
    if delta is None or not np.isfinite(float(delta)):
        return {"fillColor": "#9ca3af", "color": "#374151", "weight": 1, "fillOpacity": 0.4}
    delta = float(delta)
    # Green: model predicts shallower than IDW (improvement in many over-smoothed areas).
    # Red: model predicts deeper than IDW.
    if delta >= 1.5:
        color = "#dc2626"
    elif delta >= 0.5:
        color = "#f97316"
    elif delta <= -1.5:
        color = "#16a34a"
    elif delta <= -0.5:
        color = "#22c55e"
    else:
        color = "#eab308"
    return {"fillColor": color, "color": "#1f2937", "weight": 1, "fillOpacity": 0.65}


def _style_fn_error(feature: dict) -> dict:
    err = feature["properties"].get("abs_error_latest")
    has_obs = feature["properties"].get("has_observation_latest")
    if not has_obs or err is None or not np.isfinite(float(err)):
        return {"fillColor": "#9ca3af", "color": "#6b7280", "weight": 1, "fillOpacity": 0.15}
    err = float(err)
    if err <= 1.0:
        color = "#16a34a"
    elif err <= 2.5:
        color = "#eab308"
    elif err <= 4.0:
        color = "#f97316"
    else:
        color = "#dc2626"
    return {"fillColor": color, "color": "#1f2937", "weight": 1, "fillOpacity": 0.7}


def build_map(
    villages: gpd.GeoDataFrame,
    predictions: pd.DataFrame,
    piezometer_village: pd.DataFrame,
    streams: gpd.GeoDataFrame,
    canals: gpd.GeoDataFrame,
    tanks: gpd.GeoDataFrame,
    out_html: Path,
) -> None:
    base = villages.to_crs("EPSG:4326").copy()
    preds = predictions.copy()
    preds["date"] = pd.to_datetime(preds["date"])

    latest_date = preds["date"].max()
    latest = preds[preds["date"] == latest_date][
        ["village_id", "predicted_groundwater_xgb", "predicted_groundwater_idw", "confidence_score", "has_piezometer", "rainfall"]
    ].copy()
    latest = latest.rename(
        columns={
            "predicted_groundwater_xgb": "predicted_groundwater_xgb_latest",
            "predicted_groundwater_idw": "predicted_groundwater_idw_latest",
            "confidence_score": "confidence_score_latest",
            "has_piezometer": "has_piezometer_latest",
            "rainfall": "rainfall_latest",
        }
    )
    latest["model_minus_idw_latest"] = latest["predicted_groundwater_xgb_latest"] - latest["predicted_groundwater_idw_latest"]
    latest_obs = preds[preds["date"] == latest_date][["village_id", "groundwater_level", "predicted_groundwater_xgb"]].copy()
    latest_obs["has_observation_latest"] = pd.to_numeric(latest_obs["groundwater_level"], errors="coerce").notna().astype(int)
    latest_obs["abs_error_latest"] = np.abs(
        pd.to_numeric(latest_obs["groundwater_level"], errors="coerce")
        - pd.to_numeric(latest_obs["predicted_groundwater_xgb"], errors="coerce")
    )
    latest = latest.merge(
        latest_obs[["village_id", "has_observation_latest", "abs_error_latest"]],
        on="village_id",
        how="left",
    )
    base = base.merge(latest, on="village_id", how="left")

    base_center = base.to_crs("EPSG:32644").copy()
    base_center["geometry"] = base_center.geometry.centroid
    base_center = base_center.to_crs("EPSG:4326")
    center = [float(base_center.geometry.y.mean()), float(base_center.geometry.x.mean())]
    fmap = folium.Map(location=center, zoom_start=9, tiles="cartodbpositron")

    folium.GeoJson(
        data=json.loads(base.to_json()),
        name="Villages - Predicted GW",
        style_function=_style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=["village_name", "predicted_groundwater_xgb_latest", "confidence_score_latest", "has_piezometer_latest"],
            aliases=["Village", "Pred GW - XGBoost", "Confidence", "Has piezometer"],
            sticky=False,
        ),
    ).add_to(fmap)

    folium.GeoJson(
        data=json.loads(base.to_json()),
        name="Villages - IDW Baseline",
        style_function=_style_fn_idw,
        tooltip=folium.GeoJsonTooltip(
            fields=["village_name", "predicted_groundwater_idw_latest", "rainfall_latest"],
            aliases=["Village", "Pred GW - IDW", "Rainfall (latest month)"],
            sticky=False,
        ),
        show=False,
    ).add_to(fmap)

    folium.GeoJson(
        data=json.loads(base.to_json()),
        name="Model vs IDW Difference",
        style_function=_style_fn_model_minus_idw,
        tooltip=folium.GeoJsonTooltip(
            fields=["village_name", "model_minus_idw_latest", "predicted_groundwater_xgb_latest", "predicted_groundwater_idw_latest"],
            aliases=["Village", "Model - IDW", "Model Pred", "IDW Pred"],
            sticky=False,
        ),
        show=False,
    ).add_to(fmap)

    folium.GeoJson(
        data=json.loads(base.to_json()),
        name="Error Map (Observed Villages)",
        style_function=_style_fn_error,
        tooltip=folium.GeoJsonTooltip(
            fields=["village_name", "has_observation_latest", "abs_error_latest", "predicted_groundwater_xgb_latest", "predicted_groundwater_idw_latest"],
            aliases=["Village", "Observed in latest month", "Absolute Error", "Model Pred", "IDW Pred"],
            sticky=False,
        ),
        show=False,
    ).add_to(fmap)

    piezo_gdf = gpd.GeoDataFrame(
        piezometer_village.copy(),
        geometry=gpd.points_from_xy(piezometer_village["lon"], piezometer_village["lat"]),
        crs="EPSG:4326",
    )
    if "date" in piezo_gdf.columns:
        piezo_gdf["date"] = pd.to_datetime(piezo_gdf["date"], errors="coerce").astype(str)
    if "month" in piezo_gdf.columns:
        piezo_gdf["month"] = pd.to_datetime(piezo_gdf["month"], errors="coerce").astype(str)
    folium.GeoJson(
        data=json.loads(piezo_gdf.to_json()),
        name="Piezometer Points",
        marker=folium.CircleMarker(radius=3, color="#1d4ed8", fill=True),
    ).add_to(fmap)

    for gdf, name, color in [
        (streams, "Streams", "#0ea5e9"),
        (canals, "Canals", "#0369a1"),
        (tanks, "Tanks", "#22c55e"),
    ]:
        if gdf is None or gdf.empty:
            continue
        layer = gdf.to_crs("EPSG:4326")
        folium.GeoJson(
            data=json.loads(layer.to_json()),
            name=name,
            style_function=lambda _, c=color: {"color": c, "weight": 2, "fillOpacity": 0.2},
        ).add_to(fmap)

    # Time slider based on village monthly predictions.
    # Keep payload bounded to avoid MemoryError on large village-month tables.
    preds_recent = preds.copy()
    unique_months = sorted(preds_recent["date"].dropna().unique())
    if len(unique_months) > 36:
        keep = set(unique_months[-36:])
        preds_recent = preds_recent[preds_recent["date"].isin(keep)].copy()

    ts_geo = base[["village_id", "village_name", "geometry"]].merge(
        preds_recent[["village_id", "date", "predicted_groundwater_xgb"]],
        on="village_id",
        how="left",
    )
    ts_geo = gpd.GeoDataFrame(ts_geo, geometry="geometry", crs="EPSG:4326")
    ts_geo = ts_geo.to_crs("EPSG:32644")
    ts_geo["geometry"] = ts_geo.geometry.centroid
    ts_geo = ts_geo.to_crs("EPSG:4326")

    max_features = 50000
    if len(ts_geo) > max_features:
        stride = max(1, len(ts_geo) // max_features)
        ts_geo = ts_geo.iloc[::stride].copy()

    features = []
    for _, row in ts_geo.iterrows():
        if pd.isna(row["date"]):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"].__geo_interface__,
                "properties": {
                    "time": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                    "style": _style_fn(
                        {"properties": {"predicted_groundwater_xgb_latest": row["predicted_groundwater_xgb"]}}
                    ),
                    "popup": f"{row['village_name']}: {float(row['predicted_groundwater_xgb']):.2f}",
                },
            }
        )

    if features:
        TimestampedGeoJson(
            {"type": "FeatureCollection", "features": features},
            period="P1M",
            add_last_point=False,
            auto_play=False,
            loop=False,
            max_speed=5,
            loop_button=True,
            date_options="YYYY-MM",
            time_slider_drag_update=True,
        ).add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_html))
