import argparse
import json
import math
import re
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from .config import (
    ACTIVE_LULC_CLASSES,
    AREA_CRS,
    ARTIFACTS_DIR,
    DATA_EXPORTS_DIR,
    DATA_PROCESSED_DIR,
    DATA_RAW_DIR,
    DEFAULT_CRS,
    KRIGING_STRATEGIES,
    NOISE_CLASSES,
    REPO_ROOT,
)

try:
    from pykrige.ok import OrdinaryKriging
except Exception:  # pragma: no cover
    OrdinaryKriging = None

try:
    import rasterio
    from rasterio.mask import mask as raster_mask
except Exception:  # pragma: no cover
    rasterio = None
    raster_mask = None


@dataclass
class PreparedData:
    villages: gpd.GeoDataFrame
    train_df: pd.DataFrame
    trends_df: pd.DataFrame


PREDICTIONS_GEOJSON_PATH = DATA_EXPORTS_DIR / "map_data_predictions.geojson"
FRONTEND_PREDICTIONS_GEOJSON_PATH = REPO_ROOT / "frontend" / "public" / "data" / "map_data_predictions.geojson"


def ensure_dirs() -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    DATA_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _find_file(patterns: list[str], root: Path, suffixes: tuple[str, ...]) -> Path | None:
    for path in sorted(root.iterdir()):
        if path.suffix.lower() not in suffixes:
            continue
        name = path.name.lower()
        if any(p in name for p in patterns):
            return path
    return None


def _read_vector_from_zip(zip_path: Path, name_hint: str | None = None) -> gpd.GeoDataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        shp_names = [n for n in zf.namelist() if n.lower().endswith(".shp")]
    if not shp_names:
        raise FileNotFoundError(f"No shapefile found in {zip_path}")
    selected = shp_names[0]
    if name_hint:
        hinted = [name for name in shp_names if name_hint.lower() in name.lower()]
        if hinted:
            selected = hinted[0]
    return gpd.read_file(f"zip://{zip_path}!{selected}")


def _normalize_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf.columns = [str(c).strip().lower() for c in gdf.columns]
    return gdf


def _pick_col(columns: list[str], candidates: list[str]) -> str | None:
    for key in candidates:
        for col in columns:
            if key in col:
                return col
    return None


def _series_or_default(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce").fillna(default)
    return pd.Series(default, index=frame.index, dtype=float)


def _canonical_lulc(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    mapping = {
        "water": "Water",
        "trees": "Trees",
        "tree": "Trees",
        "flooded": "Flooded Vegetation",
        "vegetation": "Flooded Vegetation",
        "crop": "Crops",
        "crops": "Crops",
        "built": "Built Area",
        "urban": "Built Area",
        "bare": "Bare Ground",
        "snow": "Snow/Ice",
        "ice": "Snow/Ice",
        "cloud": "Clouds",
        "range": "Rangeland",
        "grass": "Rangeland",
    }
    for key, label in mapping.items():
        if key in raw:
            return label
    return None


RGB_CLASS_MAP = {
    "Water": (59, 130, 246),
    "Trees": (34, 197, 94),
    "Flooded Vegetation": (134, 239, 172),
    "Crops": (250, 204, 21),
    "Built Area": (239, 68, 68),
    "Bare Ground": (212, 212, 212),
    "Snow/Ice": (229, 231, 235),
    "Clouds": (156, 163, 175),
    "Rangeland": (252, 211, 77),
}


def _closest_lulc_from_rgb(rgb: tuple[int, int, int]) -> str:
    best = "Bare Ground"
    best_distance = math.inf
    for label, target in RGB_CLASS_MAP.items():
        d = (
            (rgb[0] - target[0]) ** 2
            + (rgb[1] - target[1]) ** 2
            + (rgb[2] - target[2]) ** 2
        )
        if d < best_distance:
            best = label
            best_distance = d
    return best


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


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


def _load_villages(raw_dir: Path) -> gpd.GeoDataFrame:
    villages_zip = _find_file(["village", "mandal"], raw_dir, (".zip",))
    if villages_zip:
        villages = _read_vector_from_zip(villages_zip, name_hint="okri_vil")
    else:
        fallback = Path("frontend/public/data/villages.geojson")
        villages = gpd.read_file(fallback)

    villages = _normalize_columns(villages)
    if villages.crs is None:
        villages = villages.set_crs(DEFAULT_CRS)
    villages = villages.to_crs(DEFAULT_CRS)

    # Keep joins deterministic regardless source ID quality/duplicates.
    villages["village_id"] = np.arange(1, len(villages) + 1, dtype=int)

    name_col = _pick_col(list(villages.columns), ["village_name", "village", "name", "dvname"])
    villages["village_name"] = villages[name_col].astype(str).str.strip() if name_col else villages["village_id"].astype(str)
    villages["district"] = (
        villages[_pick_col(list(villages.columns), ["district", "dname"])].astype(str).str.strip()
        if _pick_col(list(villages.columns), ["district", "dname"])
        else "Unknown"
    )
    villages["mandal"] = (
        villages[_pick_col(list(villages.columns), ["mandal", "taluk", "dmname", "mname"])].astype(str).str.strip()
        if _pick_col(list(villages.columns), ["mandal", "taluk", "dmname", "mname"])
        else "Unknown"
    )
    villages["district"] = villages["district"].astype(str).str.upper().str.strip()
    villages = villages[villages["district"] == "KRISHNA"].copy()
    if villages.empty:
        raise ValueError("Krishna district filter returned zero villages in model pipeline")
    return villages[["village_id", "village_name", "district", "mandal", "geometry"]]


def _lulc_vector_features(lulc: gpd.GeoDataFrame, villages: gpd.GeoDataFrame) -> pd.DataFrame:
    lulc = _normalize_columns(lulc)
    if lulc.crs is None:
        lulc = lulc.set_crs(DEFAULT_CRS)
    lulc = lulc.to_crs(villages.crs)

    class_col = _pick_col(list(lulc.columns), ["lulc", "class", "landuse", "land_use", "category"])
    if class_col is None:
        raise ValueError("Unable to identify LULC class column")

    lulc["lulc_class"] = lulc[class_col].map(_canonical_lulc)
    lulc = lulc[lulc["lulc_class"].notna()].copy()
    lulc = lulc[~lulc["lulc_class"].isin(NOISE_CLASSES)].copy()

    v_area = villages.to_crs(AREA_CRS).copy()
    l_area = lulc.to_crs(AREA_CRS).copy()

    inter = gpd.overlay(
        v_area[["village_id", "geometry"]],
        l_area[["lulc_class", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    inter = inter[inter.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    inter["part_area"] = inter.geometry.area
    totals = inter.groupby("village_id", as_index=False)["part_area"].sum().rename(columns={"part_area": "total_area"})
    by_class = inter.groupby(["village_id", "lulc_class"], as_index=False)["part_area"].sum()
    by_class = by_class.merge(totals, on="village_id", how="left")
    by_class["pct"] = np.where(by_class["total_area"] > 0, (by_class["part_area"] / by_class["total_area"]) * 100.0, 0.0)

    pivot = by_class.pivot_table(index="village_id", columns="lulc_class", values="pct", aggfunc="sum", fill_value=0.0)
    pivot.columns = [f"{c.lower().replace(' ', '_').replace('/', '_')}_pct" for c in pivot.columns]
    for klass in ACTIVE_LULC_CLASSES:
        key = f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct"
        if key not in pivot.columns:
            pivot[key] = 0.0
    pivot = pivot.reset_index()
    return pivot


def _extract_raster_paths(zip_path: Path) -> list[Path]:
    stable_dir = DATA_PROCESSED_DIR / "lulc_rasters"
    stable_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith((".tif", ".tiff"))]
        for member in members:
            basename = Path(member).name
            dest = stable_dir / basename
            with zf.open(member) as src, dest.open("wb") as dst:
                dst.write(src.read())
            extracted.append(dest)
    return extracted


def _lulc_raster_features(raster_path: Path, villages: gpd.GeoDataFrame) -> pd.DataFrame:
    if rasterio is None or raster_mask is None:
        raise RuntimeError("Rasterio is required for raster LULC processing")

    rows: list[dict] = []
    with rasterio.open(raster_path) as src:
        village_proj = villages.to_crs(src.crs or DEFAULT_CRS)
        for _, village in village_proj.iterrows():
            geom = [village.geometry.__geo_interface__]
            try:
                clipped, _ = raster_mask(src, geom, crop=True, filled=False)
            except Exception:
                rows.append({"village_id": int(village.village_id)})
                continue

            counts = {klass: 0 for klass in ACTIVE_LULC_CLASSES}
            if clipped.ndim == 3 and clipped.shape[0] >= 3:
                # RGB raster case.
                valid = ~clipped[0].mask
                if valid.sum() == 0:
                    rows.append({"village_id": int(village.village_id)})
                    continue
                r = np.asarray(clipped[0].data[valid], dtype=np.uint8)
                g = np.asarray(clipped[1].data[valid], dtype=np.uint8)
                b = np.asarray(clipped[2].data[valid], dtype=np.uint8)
                rgb = np.stack([r, g, b], axis=1)
                unique, freq = np.unique(rgb, axis=0, return_counts=True)
                for rgb_val, count in zip(unique, freq):
                    klass = _closest_lulc_from_rgb((int(rgb_val[0]), int(rgb_val[1]), int(rgb_val[2])))
                    if klass in counts:
                        counts[klass] += int(count)
            else:
                # Single-band categorical fallback.
                band = np.asarray(clipped[0].filled(np.nan), dtype=float)
                valid = np.isfinite(band)
                if valid.sum() == 0:
                    rows.append({"village_id": int(village.village_id)})
                    continue
                vals, freq = np.unique(band[valid].astype(int), return_counts=True)
                code_map = {
                    1: "Water",
                    2: "Trees",
                    3: "Flooded Vegetation",
                    4: "Crops",
                    5: "Built Area",
                    6: "Bare Ground",
                    7: "Snow/Ice",
                    8: "Clouds",
                    9: "Rangeland",
                }
                for val, count in zip(vals, freq):
                    klass = code_map.get(int(val))
                    if klass and klass in counts:
                        counts[klass] += int(count)

            total = sum(counts.values())
            row = {"village_id": int(village.village_id)}
            for klass in ACTIVE_LULC_CLASSES:
                key = f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct"
                row[key] = (counts[klass] / total * 100.0) if total > 0 else 0.0
            rows.append(row)

    return pd.DataFrame(rows)


def _extract_year(path: Path) -> int | None:
    m = re.search(r"(20\d{2})", path.stem)
    if m:
        return int(m.group(1))
    m2 = re.search(r"[_-](\d{2})$", path.stem)
    if m2:
        return 2000 + int(m2.group(1))
    return None


def _synthetic_lulc_features(villages: gpd.GeoDataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    cols = [f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct" for klass in ACTIVE_LULC_CLASSES]
    for _, row in villages.iterrows():
        raw = rng.dirichlet(np.ones(len(cols)))
        values = (raw * 100.0).tolist()
        out = {"village_id": int(row["village_id"])}
        for col, val in zip(cols, values):
            out[col] = float(val)
        rows.append(out)
    return pd.DataFrame(rows)


def _load_lulc_timeseries(raw_dir: Path, villages: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    lulc_files = sorted([p for p in raw_dir.iterdir() if p.suffix.lower() == ".zip" and "lulc" in p.name.lower()])
    if not lulc_files:
        raise FileNotFoundError("No LULC zip found in data/raw")

    snapshots: list[pd.DataFrame] = []
    for i, file_path in enumerate(lulc_files):
        year = _extract_year(file_path) or (2024 + i)
        try:
            try:
                lulc = _read_vector_from_zip(file_path)
                features = _lulc_vector_features(lulc, villages)
                features["year"] = year
                snapshots.append(features)
            except FileNotFoundError:
                rasters = _extract_raster_paths(file_path)
                if not rasters:
                    raise
                for idx, raster_path in enumerate(rasters):
                    raster_year = _extract_year(raster_path) or (year + idx)
                    if rasterio is None or raster_mask is None:
                        warnings.warn(
                            "Rasterio unavailable: generating synthetic LULC percentages. "
                            "Install rasterio for strict zonal clipping."
                        )
                        features = _synthetic_lulc_features(villages, seed=raster_year)
                    else:
                        features = _lulc_raster_features(raster_path, villages)
                    features["year"] = raster_year
                    snapshots.append(features)
        except Exception as exc:  # pragma: no cover
            warnings.warn(f"Skipping LULC file {file_path.name}: {exc}")

    if not snapshots:
        raise RuntimeError("No valid LULC snapshots could be processed")

    all_snapshots = pd.concat(snapshots, ignore_index=True)
    latest_year = int(all_snapshots["year"].max())
    latest = all_snapshots[all_snapshots["year"] == latest_year].drop(columns=["year"]).copy()

    trends = pd.DataFrame({"village_id": sorted(all_snapshots["village_id"].unique())})
    if all_snapshots["year"].nunique() > 1:
        first_year = int(all_snapshots["year"].min())
        base = all_snapshots[all_snapshots["year"] == first_year][["village_id", "built_area_pct"]]
        curr = all_snapshots[all_snapshots["year"] == latest_year][["village_id", "built_area_pct"]]
        trends = trends.merge(base.rename(columns={"built_area_pct": "built_area_pct_start"}), on="village_id", how="left")
        trends = trends.merge(curr.rename(columns={"built_area_pct": "built_area_pct_end"}), on="village_id", how="left")
        trends["built_up_change_pct"] = trends["built_area_pct_end"].fillna(0) - trends["built_area_pct_start"].fillna(0)
        trends["lulc_trend_available"] = True
        trends["trend_window"] = f"{first_year}-{latest_year}"
    else:
        trends["built_area_pct_start"] = np.nan
        trends["built_area_pct_end"] = np.nan
        trends["built_up_change_pct"] = np.nan
        trends["lulc_trend_available"] = False
        trends["trend_window"] = "single-snapshot"

    return latest, trends


def _load_excel_features(raw_dir: Path, villages: gpd.GeoDataFrame) -> pd.DataFrame:
    village_key = villages[["village_id", "village_name"]].copy()
    village_key["village_name_norm"] = village_key["village_name"].str.lower().str.strip()
    village_lookup = (
        village_key.drop_duplicates(subset=["village_name_norm"])
        .set_index("village_name_norm")["village_id"]
        .to_dict()
    )

    pumping_path = _find_file(["pumping"], raw_dir, (".xlsx", ".xls"))
    piezo_path = _find_file(["pzwater", "waterlevel", "piez"], raw_dir, (".xlsx", ".xls"))

    pump_df = pd.DataFrame(columns=["village_id", "pumping_rate"])
    if pumping_path:
        pdf = pd.read_excel(pumping_path)
        pdf.columns = [str(c).strip().lower() for c in pdf.columns]
        id_col = _pick_col(list(pdf.columns), ["village_id", "villageid", "id"])
        village_col = _pick_col(list(pdf.columns), ["village", "name"])
        pump_col = _pick_col(list(pdf.columns), ["pumping", "draft", "rate"])
        if pump_col:
            fields = [pump_col]
            if id_col:
                fields.append(id_col)
            if village_col:
                fields.append(village_col)
            temp = pdf[fields].copy()
            temp["pumping_rate"] = pd.to_numeric(temp[pump_col], errors="coerce")
            if id_col:
                temp["village_id"] = pd.to_numeric(temp[id_col], errors="coerce")
            else:
                temp["village_id"] = np.nan
            if village_col:
                temp["village_name_norm"] = temp[village_col].astype(str).str.lower().str.strip()
                temp.loc[temp["village_id"].isna(), "village_id"] = temp.loc[
                    temp["village_id"].isna(), "village_name_norm"
                ].map(village_lookup)
            temp["pumping_rate"] = pd.to_numeric(temp["pumping_rate"], errors="coerce")
            temp = temp.dropna(subset=["pumping_rate", "village_id"])
            temp["village_id"] = temp["village_id"].astype(int)
            pump_df = temp.groupby("village_id", as_index=False)["pumping_rate"].mean()

    pz_df = pd.DataFrame(columns=["village_id", "groundwater_level"])
    if piezo_path:
        zdf = pd.read_excel(piezo_path)
        zdf.columns = [str(c).strip().lower() for c in zdf.columns]
        id_col = _pick_col(list(zdf.columns), ["village_id", "villageid", "id"])
        village_col = _pick_col(list(zdf.columns), ["village", "location", "name"])
        level_col = _pick_col(list(zdf.columns), ["water level", "groundwater", "depth", "wl"])
        if level_col:
            fields = [level_col]
            if id_col:
                fields.append(id_col)
            if village_col:
                fields.append(village_col)
            temp = zdf[fields].copy()
            temp["groundwater_level"] = pd.to_numeric(temp[level_col], errors="coerce")
            if id_col:
                temp["village_id"] = pd.to_numeric(temp[id_col], errors="coerce")
            else:
                temp["village_id"] = np.nan
            if village_col:
                temp["village_name_norm"] = temp[village_col].astype(str).str.lower().str.strip()
                temp.loc[temp["village_id"].isna(), "village_id"] = temp.loc[
                    temp["village_id"].isna(), "village_name_norm"
                ].map(village_lookup)
            temp["groundwater_level"] = pd.to_numeric(temp["groundwater_level"], errors="coerce")
            temp = temp.dropna(subset=["groundwater_level", "village_id"])
            temp["village_id"] = temp["village_id"].astype(int)
            pz_df = temp.groupby("village_id", as_index=False)["groundwater_level"].mean()

    merged = village_key[["village_id"]].drop_duplicates().merge(pump_df, on="village_id", how="left").merge(
        pz_df, on="village_id", how="left"
    )
    pump_med = merged["pumping_rate"].median()
    gw_med = merged["groundwater_level"].median()
    merged["pumping_rate"] = merged["pumping_rate"].fillna(0.0 if pd.isna(pump_med) else float(pump_med))
    merged["groundwater_level"] = merged["groundwater_level"].fillna(10.0 if pd.isna(gw_med) else float(gw_med))
    return merged


def build_feature_table(raw_dir: Path = DATA_RAW_DIR) -> PreparedData:
    ensure_dirs()
    villages = _load_villages(raw_dir)
    lulc_latest, trends = _load_lulc_timeseries(raw_dir, villages)
    excel_features = _load_excel_features(raw_dir, villages)

    table = villages.drop(columns=["geometry"]).merge(lulc_latest, on="village_id", how="left").merge(excel_features, on="village_id", how="left")

    table["rainfall_mm"] = np.nan
    table["recharge_factor"] = np.clip(
        0.5 + table.get("water_pct", 0) * 0.005 + table.get("trees_pct", 0) * 0.004 + table.get("rangeland_pct", 0) * 0.003,
        0.2,
        2.5,
    )

    table["infiltration_score"] = (
        table.get("water_pct", 0) * 0.9
        + table.get("trees_pct", 0) * 0.8
        + table.get("crops_pct", 0) * 0.6
        - table.get("built_area_pct", 0) * 0.9
    )
    table["groundwater_stress"] = table["pumping_rate"] / table["recharge_factor"].replace(0, np.nan)
    table["groundwater_stress"] = table["groundwater_stress"].replace([np.inf, -np.inf], np.nan).fillna(0)
    table["rainfall_proxy"] = _series_or_default(table, "flooded_vegetation_pct")
    table["recharge_index"] = (
        _series_or_default(table, "water_pct")
        + _series_or_default(table, "tank_count")
        + table["rainfall_proxy"]
    )
    table["extraction_stress"] = (
        _series_or_default(table, "pumping_rate")
        / (_series_or_default(table, "wells_total") + 1.0)
    )
    table["terrain_gradient"] = (
        _series_or_default(table, "elevation_max")
        - _series_or_default(table, "elevation_min")
    )
    aquifer_types = table["aquifer_type"] if "aquifer_type" in table.columns else pd.Series("Unknown", index=table.index)
    table["aquifer_storage_factor"] = aquifer_types.map(_aquifer_storage_factor)

    features_path = DATA_PROCESSED_DIR / "village_features.parquet"
    table.to_parquet(features_path, index=False)

    villages_geo = villages.merge(
        table.drop(columns=["village_name", "district", "mandal"], errors="ignore"),
        on="village_id",
        how="left",
    )
    villages_geo.to_file(DATA_PROCESSED_DIR / "villages_with_features.geojson", driver="GeoJSON")

    trends.to_csv(DATA_EXPORTS_DIR / "lulc_trends.csv", index=False)
    return PreparedData(villages=villages_geo, train_df=table, trends_df=trends)


def _kriging_predict(train_xy: np.ndarray, train_values: np.ndarray, query_xy: np.ndarray) -> np.ndarray:
    if OrdinaryKriging is None:
        return np.zeros(len(query_xy))
    ok = OrdinaryKriging(
        train_xy[:, 0],
        train_xy[:, 1],
        train_values,
        variogram_model="spherical",
        verbose=False,
        enable_plotting=False,
    )
    preds = []
    for x, y in query_xy:
        z, _ = ok.execute("points", np.array([x]), np.array([y]))
        preds.append(float(z[0]))
    return np.asarray(preds)


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
    if n == 0:
        return pd.DataFrame(
            columns=[
                "nearest_piezometer_distance_km",
                "nearby_observation_count",
                "neighboring_prediction_variance",
                "confidence_distance_component",
                "confidence_density_component",
                "confidence_variance_component",
                "confidence",
            ]
        )

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


def train_and_predict(data: PreparedData, kriging_strategy: str = "residual") -> tuple[gpd.GeoDataFrame, dict]:
    if kriging_strategy not in KRIGING_STRATEGIES:
        raise ValueError(f"kriging_strategy must be one of {sorted(KRIGING_STRATEGIES)}")

    frame = data.train_df.copy()
    target = "groundwater_level"
    feature_cols = [
        "water_pct",
        "trees_pct",
        "flooded_vegetation_pct",
        "crops_pct",
        "built_area_pct",
        "bare_ground_pct",
        "rangeland_pct",
        "pumping_rate",
        "recharge_factor",
        "infiltration_score",
        "groundwater_stress",
        "recharge_index",
        "extraction_stress",
        "terrain_gradient",
        "aquifer_storage_factor",
    ]

    for col in feature_cols:
        if col not in frame.columns:
            frame[col] = 0.0
    feature_medians = frame[feature_cols].median(numeric_only=True).fillna(0.0)
    frame[feature_cols] = frame[feature_cols].fillna(feature_medians)
    observed_mask = frame[target].notna()
    observed_by_village = pd.Series(observed_mask.to_numpy(dtype=bool), index=frame["village_id"].to_numpy())
    target_median = frame[target].median()
    frame[target] = frame[target].fillna(10.0 if pd.isna(target_median) else float(target_median))

    X_train, X_test, y_train, y_test = train_test_split(frame[feature_cols], frame[target], test_size=0.2, random_state=42)

    model = xgb.XGBRegressor(
        n_estimators=400,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        objective="reg:squarederror",
        eval_metric="rmse",
    )
    model.fit(X_train, y_train)

    y_pred_test = model.predict(X_test)
    metrics = {
        "mae": float(mean_absolute_error(y_test, y_pred_test)),
        "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
        "r2": float(r2_score(y_test, y_pred_test)),
        "rows": int(len(frame)),
        "kriging_strategy": kriging_strategy,
    }

    gdf = data.villages.copy()
    base_pred = model.predict(frame[feature_cols])
    gdf["xgb_prediction"] = base_pred

    centroids = gdf.to_crs(AREA_CRS).centroid.to_crs(DEFAULT_CRS)
    xy = np.column_stack([centroids.x.values, centroids.y.values])

    if OrdinaryKriging is not None:
        if kriging_strategy == "residual":
            residuals = frame[target].values - base_pred
            correction = _kriging_predict(xy, residuals, xy)
            final_pred = base_pred + correction
            gdf["kriging_correction"] = correction
        else:
            final_pred = _kriging_predict(xy, frame[target].values, xy)
            gdf["kriging_correction"] = final_pred - base_pred
    else:
        final_pred = base_pred
        gdf["kriging_correction"] = 0.0
        metrics["kriging_warning"] = "PyKrige unavailable. Returned XGBoost predictions without kriging correction."

    gdf["predicted_groundwater_level"] = final_pred
    centroids_area = gdf.to_crs(AREA_CRS).centroid
    confidence_support = _compute_confidence_support(
        centroids_area=centroids_area,
        observed_mask=gdf["village_id"].map(observed_by_village).fillna(False),
        predictions=np.asarray(final_pred, dtype=float),
    )
    for col in confidence_support.columns:
        gdf[col] = confidence_support[col].values

    metrics["confidence_method"] = "0.45*distance + 0.35*obs_density + 0.20*inverse_prediction_variance"
    metrics["confidence_radius_km"] = 15.0
    metrics["confidence_neighbor_k"] = 5
    gdf["risk_score"] = gdf["predicted_groundwater_level"] * 5
    gdf["risk_level"] = gdf["risk_score"].apply(
        lambda x: "high" if x > 60 else "medium" if x > 30 else "low"
    )
    rainfall_factor = pd.to_numeric(frame.get("rainfall_mm", 0.0), errors="coerce").fillna(0.0) * 0.001
    pumping_factor = pd.to_numeric(frame.get("pumping_rate", 0.0), errors="coerce").fillna(0.0) * 0.01
    gdf["forecast_3m"] = gdf["predicted_groundwater_level"] + rainfall_factor.values - pumping_factor.values
    gdf["forecast_6m"] = gdf["forecast_3m"] + rainfall_factor.values - pumping_factor.values
    gdf["anomaly_flag"] = "normal"
    gdf["recharge_potential"] = "medium"

    gdf.drop(columns=[c for c in ["xgb_prediction"] if c in gdf.columns], inplace=True)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(ARTIFACTS_DIR / "model_xgb.json"))
    (ARTIFACTS_DIR / "feature_columns.json").write_text(json.dumps(feature_cols, indent=2))
    (ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (ARTIFACTS_DIR / "run_metadata.json").write_text(
        json.dumps(
            {
                "kriging_strategy": kriging_strategy,
                "has_kriging": OrdinaryKriging is not None,
                "rows": len(gdf),
                "columns": sorted(gdf.columns),
            },
            indent=2,
        )
    )

    out_cols = [
        "village_id",
        "village_name",
        "district",
        "mandal",
        "predicted_groundwater_level",
        "confidence",
        "nearest_piezometer_distance_km",
        "nearby_observation_count",
        "neighboring_prediction_variance",
        "risk_level",
        "risk_score",
        "forecast_3m",
        "forecast_6m",
        "anomaly_flag",
        "recharge_potential",
        "water_pct",
        "trees_pct",
        "flooded_vegetation_pct",
        "crops_pct",
        "built_area_pct",
        "bare_ground_pct",
        "rangeland_pct",
        "infiltration_score",
        "groundwater_stress",
        "recharge_index",
        "extraction_stress",
        "terrain_gradient",
        "aquifer_storage_factor",
        "geometry",
    ]
    export = gdf[out_cols].copy()
    export["district"] = export["district"].astype(str).str.upper().str.strip()
    export = export[export["district"] == "KRISHNA"].copy()
    assert export["district"].nunique() == 1
    FRONTEND_PREDICTIONS_GEOJSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    export.to_file(PREDICTIONS_GEOJSON_PATH, driver="GeoJSON")
    export.to_file(FRONTEND_PREDICTIONS_GEOJSON_PATH, driver="GeoJSON")
    export.drop(columns=["geometry"]).to_parquet(DATA_EXPORTS_DIR / "predictions.parquet", index=False)

    return export, metrics


def attach_trend_flags(export_gdf: gpd.GeoDataFrame, trends_df: pd.DataFrame) -> gpd.GeoDataFrame:
    merged = export_gdf.merge(
        trends_df[["village_id", "built_up_change_pct", "lulc_trend_available", "trend_window"]],
        on="village_id",
        how="left",
    )
    merged["groundwater_decline"] = merged["predicted_groundwater_level"] > merged["predicted_groundwater_level"].median()
    merged["high_built_up_growth"] = merged["built_up_change_pct"].fillna(0) > merged["built_up_change_pct"].fillna(0).quantile(0.75)
    merged["urban_growth_risk_flag"] = merged["groundwater_decline"] & merged["high_built_up_growth"]
    merged.to_file(PREDICTIONS_GEOJSON_PATH, driver="GeoJSON")
    merged.to_file(FRONTEND_PREDICTIONS_GEOJSON_PATH, driver="GeoJSON")
    return merged


def run_pipeline(raw_dir: Path = DATA_RAW_DIR, kriging_strategy: str = "residual") -> dict:
    prepared = build_feature_table(raw_dir)
    export_gdf, metrics = train_and_predict(prepared, kriging_strategy=kriging_strategy)
    attach_trend_flags(export_gdf, prepared.trends_df)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Groundwater AI pipeline")
    parser.add_argument("--raw-dir", type=Path, default=DATA_RAW_DIR)
    parser.add_argument("--kriging-strategy", choices=sorted(KRIGING_STRATEGIES), default="residual")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    report = run_pipeline(raw_dir=args.raw_dir, kriging_strategy=args.kriging_strategy)
    print(json.dumps(report, indent=2))

