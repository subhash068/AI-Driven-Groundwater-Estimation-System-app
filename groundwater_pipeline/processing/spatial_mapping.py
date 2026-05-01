from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd

from groundwater_pipeline.data.loaders import LoadedData, DEFAULT_CRS

AREA_CRS = "EPSG:32644"


def ensure_village_or_grid(villages: gpd.GeoDataFrame, fallback_from: gpd.GeoDataFrame, cell_deg: float = 0.05) -> gpd.GeoDataFrame:
    if not villages.empty:
        return villages.to_crs(DEFAULT_CRS)

    minx, miny, maxx, maxy = fallback_from.to_crs(DEFAULT_CRS).total_bounds
    xs = np.arange(minx, maxx, cell_deg)
    ys = np.arange(miny, maxy, cell_deg)

    grid_polys = []
    for x in xs:
        for y in ys:
            grid_polys.append(
                gpd.GeoSeries.from_wkt(
                    [f"POLYGON(({x} {y}, {x+cell_deg} {y}, {x+cell_deg} {y+cell_deg}, {x} {y+cell_deg}, {x} {y}))"]
                ).iloc[0]
            )
    grid = gpd.GeoDataFrame(geometry=grid_polys, crs=DEFAULT_CRS)
    grid["village_id"] = np.arange(1, len(grid) + 1, dtype=int)
    grid["village_name"] = [f"Grid_{i}" for i in grid["village_id"]]
    grid["village_key"] = grid["village_name"].str.lower()
    return grid[["village_id", "village_name", "village_key", "geometry"]]


def map_piezometer_to_village(villages: gpd.GeoDataFrame, piezometer: pd.DataFrame) -> pd.DataFrame:
    points = gpd.GeoDataFrame(
        piezometer.copy(),
        geometry=gpd.points_from_xy(piezometer["lon"], piezometer["lat"]),
        crs=DEFAULT_CRS,
    )
    joined = gpd.sjoin(points, villages[["village_id", "geometry"]], how="left", predicate="within")

    unmatched = joined["village_id"].isna()
    if unmatched.any():
        nearest = gpd.sjoin_nearest(
            joined.loc[unmatched, ["geometry"]],
            villages[["village_id", "geometry"]],
            how="left",
            distance_col="distance_deg",
        )
        joined.loc[unmatched, "village_id"] = nearest["village_id"].values

    joined["village_id"] = pd.to_numeric(joined["village_id"], errors="coerce")
    joined = joined.dropna(subset=["village_id"]).copy()
    joined["village_id"] = joined["village_id"].astype(int)
    return pd.DataFrame(joined.drop(columns=["index_right"], errors="ignore"))


def map_polygon_class_to_village(
    villages: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    class_candidates: list[str],
    out_col: str,
) -> pd.DataFrame:
    poly = polygons.copy()
    poly.columns = [str(col) for col in poly.columns]
    class_col = None
    for col in poly.columns:
        if any(cand in col.lower() for cand in class_candidates):
            class_col = col
            break
    if class_col is None:
        return pd.DataFrame({"village_id": villages["village_id"], out_col: "Unknown"})

    poly = poly[[class_col, "geometry"]].copy()
    poly = poly.rename(columns={class_col: out_col})

    v_area = villages[["village_id", "geometry"]].to_crs(AREA_CRS)
    p_area = poly.to_crs(AREA_CRS)

    inter = gpd.overlay(v_area, p_area, how="intersection", keep_geom_type=False)
    if inter.empty:
        return pd.DataFrame({"village_id": villages["village_id"], out_col: "Unknown"})

    inter = inter[inter.geometry.notna()].copy()
    inter["area"] = inter.geometry.area
    dominant = inter.sort_values("area", ascending=False).drop_duplicates("village_id")
    out = dominant[["village_id", out_col]].copy()
    return villages[["village_id"]].merge(out, on="village_id", how="left").fillna({out_col: "Unknown"})


def map_rainfall_to_village(villages: gpd.GeoDataFrame, rainfall: pd.DataFrame) -> pd.DataFrame:
    # Rainfall is already village-linked or district-broadcasted in loader.
    out = rainfall.copy()
    out["village_id"] = out["village_id"].astype(int)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    out = out.dropna(subset=["date", "rainfall_mm"])
    return out.groupby(["village_id", "date"], as_index=False)["rainfall_mm"].sum()


def build_mapped_tables(data: LoadedData) -> dict[str, pd.DataFrame | gpd.GeoDataFrame]:
    villages = ensure_village_or_grid(data.villages, fallback_from=data.aquifer)
    piezo_mapped = map_piezometer_to_village(villages, data.piezometer)
    rain_mapped = map_rainfall_to_village(villages, data.rainfall)
    aquifer_by_village = map_polygon_class_to_village(villages, data.aquifer, ["aqui", "geo_class", "type"], "aquifer_type")
    lulc_by_village = map_polygon_class_to_village(villages, data.lulc, ["lulc", "class", "land_use", "landuse"], "lulc_class")

    return {
        "villages": villages,
        "piezometer_village": piezo_mapped,
        "rainfall_village": rain_mapped,
        "aquifer_village": aquifer_by_village,
        "lulc_village": lulc_by_village,
    }
