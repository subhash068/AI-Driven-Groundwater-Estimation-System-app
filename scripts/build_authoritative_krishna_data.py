from __future__ import annotations

import json
import math
import re
import zipfile
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image
from shapely import contains_xy


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "_staging"
FRONTEND_DATA = ROOT / "frontend" / "public" / "data"
EXPORTS = ROOT / "data" / "exports"
OUTPUT = ROOT / "output"
Image.MAX_IMAGE_PIXELS = None
GW_PUBLIC_START = pd.Timestamp("1998-01-01")
GW_PUBLIC_END = pd.Timestamp("2024-12-01")

LULC_CLASS_MAP = {
    0: "water",
    1: "water",
    2: "trees",
    4: "flooded_vegetation",
    5: "crops",
    7: "built_area",
    8: "bare_ground",
    9: "snow_ice",
    10: "clouds",
    11: "rangeland",
}

LULC_CLASS_ORDER = [
    "water",
    "trees",
    "flooded_vegetation",
    "crops",
    "built_area",
    "bare_ground",
    "snow_ice",
    "clouds",
    "rangeland",
]

ALLOWED_DISTRICTS = {"KRISHNA", "NTR"}

VILLAGE_BOUNDARY_SOURCES = [
    {
        "district": "KRISHNA",
        "zip": "Village_Mandal_DEM_Soils_MITanks_Krishna.zip",
        "staging": "Village_Krishna",
    },
    {
        "district": "NTR",
        "zip": "Village_Mandal_DEM_Soils_MITanks_NTR.zip",
        "staging": "Village_NTR",
    },
]


def norm_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def canonical_name(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def canonical_district(value: object) -> str:
    text = canonical_name(value).upper()
    collapsed = re.sub(r"[^A-Z0-9]+", "", text)
    if collapsed in {"NTR", "NTRDISTRICT", "NTRDIST", "NTRDT"}:
        return "NTR"
    return text


def allowed_district(value: object) -> bool:
    return canonical_district(value) in ALLOWED_DISTRICTS


def build_join_key(district: object, mandal: object, village_name: object) -> str:
    return "|".join(
        [
            norm_text(canonical_district(district)),
            norm_text(canonical_name(mandal)),
            norm_text(canonical_name(village_name)),
        ]
    )


def mode_or_unknown(values: pd.Series, default: str = "Unknown") -> str:
    cleaned = values.dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]
    if cleaned.empty:
        return default
    mode = cleaned.mode()
    return str(mode.iloc[0]).strip() if not mode.empty else str(cleaned.iloc[0]).strip()


def series_pairs(labels: list[str], values: list[float | None]) -> list[dict[str, object]]:
    return [{"date": label, "depth": value} for label, value in zip(labels, values, strict=False)]


def finite_values_and_indices(values: list[float | None]) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray([np.nan if value is None else float(value) for value in values], dtype=float)
    mask = np.isfinite(arr)
    return arr[mask], np.flatnonzero(mask)


def compute_trend_slope(values: list[float | None]) -> float | None:
    finite_values, finite_indices = finite_values_and_indices(values)
    if finite_values.size < 2:
        return None
    slope = np.polyfit(finite_indices.astype(float), finite_values.astype(float), 1)[0]
    return round(float(slope), 6) if np.isfinite(slope) else None


def compute_long_term_avg(values: list[float | None]) -> float | None:
    finite_values = [float(value) for value in values if value is not None and np.isfinite(float(value))]
    if not finite_values:
        return None
    return round(float(np.mean(finite_values)), 4)


def compute_seasonal_variation(values: list[float | None], labels: list[str]) -> float | None:
    month_buckets: dict[int, list[float]] = {}
    for label, value in zip(labels, values, strict=False):
        if value is None:
            continue
        numeric = float(value)
        if not np.isfinite(numeric):
            continue
        parsed = pd.to_datetime(label, errors="coerce")
        if pd.isna(parsed):
            continue
        month_buckets.setdefault(int(parsed.month), []).append(numeric)
    if len(month_buckets) < 2:
        return None
    monthly_means = [float(np.mean(bucket)) for bucket in month_buckets.values() if bucket]
    if len(monthly_means) < 2:
        return None
    seasonal = float(np.std(monthly_means))
    return round(seasonal, 4) if np.isfinite(seasonal) else None


def available_years_from_labels(labels: list[str]) -> list[int]:
    years = {
        int(label[:4])
        for label in labels
        if isinstance(label, str) and len(label) >= 4 and label[:4].isdigit()
    }
    return sorted(years)


def ensure_unzipped(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.glob("*")):
        return
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)


def find_file(root: Path, pattern: str) -> Path:
    for path in root.rglob(pattern):
        return path
    raise FileNotFoundError(f"Could not find {pattern} under {root}")


def find_first_matching_file(root: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        try:
            return find_file(root, pattern)
        except FileNotFoundError:
            continue
    return None


def read_village_boundaries() -> gpd.GeoDataFrame:
    native = read_village_boundaries_native()
    gdf = native.to_crs("EPSG:4326")
    centroid_proj = gdf.to_crs("EPSG:32644").geometry.centroid
    centroid_geo = gpd.GeoSeries(centroid_proj, crs="EPSG:32644").to_crs("EPSG:4326")
    gdf["centroid_lon"] = centroid_geo.x
    gdf["centroid_lat"] = centroid_geo.y
    return gdf


def _read_single_village_boundary_source(source: dict[str, str]) -> gpd.GeoDataFrame | None:
    zip_name = source.get("zip", "")
    district_name = source.get("district", "Unknown")
    staging_name = source.get("staging", district_name)
    zip_path = RAW / zip_name
    if not zip_path.exists():
        print(f"[INFO] Skipping {district_name} village boundaries: missing {zip_name}")
        return None

    staging_root = STAGING / staging_name
    ensure_unzipped(zip_path, staging_root)
    shp = find_first_matching_file(
        staging_root,
        [
            "*_Vil.shp",
            "*Vil*.shp",
            "*Village*.shp",
            "*.shp",
        ],
    )
    if shp is None:
        print(f"[WARN] Skipping {district_name}: no village shapefile found under {zip_name}")
        return None

    gdf = gpd.read_file(shp)
    gdf = gdf.rename(
        columns={
            "DNAME": "district",
            "DMNAME": "mandal",
            "DVNAME": "village_name",
            "DCODE": "district_code",
            "MCODE": "mandal_code",
            "VCODE": "village_code",
            "DMV_CODE": "dmv_code",
            "Area": "area_m2_source",
            "areaha": "area_ha_source",
        }
    )
    required_cols = {"district", "mandal", "village_name"}
    if not required_cols.issubset(set(gdf.columns)):
        missing = sorted(required_cols - set(gdf.columns))
        print(f"[WARN] Skipping {district_name}: missing columns in shapefile {shp.name}: {missing}")
        return None

    gdf["district"] = gdf["district"].map(canonical_district)
    gdf["mandal"] = gdf["mandal"].map(canonical_name).str.upper()
    gdf["village_name"] = gdf["village_name"].map(canonical_name)
    gdf = gdf[gdf["district"].map(allowed_district)].copy()
    if gdf.empty:
        print(f"[WARN] Skipping {district_name}: no rows after district normalization/filtering")
        return None

    gdf["state"] = "Andhra Pradesh"
    return gdf


def read_village_boundaries_native() -> gpd.GeoDataFrame:
    frames: list[gpd.GeoDataFrame] = []
    for source in VILLAGE_BOUNDARY_SOURCES:
        gdf = _read_single_village_boundary_source(source)
        if gdf is not None and not gdf.empty:
            frames.append(gdf)

    if not frames:
        raise FileNotFoundError(
            "No usable village boundary shapefiles found. "
            "Expected at least one of: "
            + ", ".join(source["zip"] for source in VILLAGE_BOUNDARY_SOURCES)
        )

    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    gdf["join_key"] = gdf.apply(
        lambda row: build_join_key(row.get("district"), row.get("mandal"), row.get("village_name")),
        axis=1,
    )
    gdf = gdf.sort_values("join_key", kind="mergesort")
    gdf = gdf.drop_duplicates(subset=["join_key"], keep="first").reset_index(drop=True)
    gdf["village_id"] = np.arange(1, len(gdf) + 1)
    return gdf


def read_aquifers() -> gpd.GeoDataFrame:
    ensure_unzipped(RAW / "Aquifers_Krishna.zip", STAGING / "Aquifers")
    shp = find_file(STAGING / "Aquifers", "Aquifers_Krishna.shp")
    gdf = gpd.read_file(shp)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4044", allow_override=True)
    gdf_utm = gdf.to_crs("EPSG:32644")
    gdf["area"] = (gdf_utm.area / 1_000_000).round(2)
    return gdf.to_crs("EPSG:4326")


def read_geomorphology() -> gpd.GeoDataFrame:
    ensure_unzipped(RAW / "GM_Krishna.zip", STAGING / "GM")
    shp = find_file(STAGING / "GM", "GM_Krishna.shp")
    gdf = gpd.read_file(shp)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    gdf = gdf.to_crs("EPSG:4326")
    gdf["geomorphology"] = gdf.get("FIN_DESC", gdf.get("DISCRIPTIO", "Unknown")).fillna("Unknown")
    return gdf[["geomorphology", "geometry"]]


def _read_world_file(path: Path) -> tuple[float, float, float, float, float, float]:
    vals = [float(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(vals) != 6:
        raise ValueError(f"Invalid world file: {path}")
    return tuple(vals)  # A, D, B, E, C, F


def _sample_lulc_for_geometry(
    geom,
    raster: np.ndarray,
    transform: tuple[float, float, float, float, float, float],
) -> dict[str, int]:
    if geom is None or geom.is_empty:
        return {}

    a, d, b, e, c, f = transform
    if b != 0.0 or d != 0.0:
        # Current source rasters are axis-aligned; reject rotated transforms for correctness.
        raise ValueError("Rotated world transform is not supported")

    h, w = raster.shape
    minx, miny, maxx, maxy = geom.bounds

    col0 = max(0, int(math.floor((minx - c) / a)))
    col1 = min(w, int(math.ceil((maxx - c) / a)) + 1)
    row0 = max(0, int(math.floor((maxy - f) / e)))
    row1 = min(h, int(math.ceil((miny - f) / e)) + 1)
    if col0 >= col1 or row0 >= row1:
        return {}

    sub = raster[row0:row1, col0:col1]
    if sub.size == 0:
        return {}

    # Sample pixel centers to avoid edge bias from world-file origin.
    xs = c + a * (np.arange(col0, col1) + 0.5)
    ys = f + e * (np.arange(row0, row1) + 0.5)
    xv, yv = np.meshgrid(xs, ys)
    inside = contains_xy(geom, xv, yv)
    vals = sub[inside]
    vals = vals[vals != 255]
    if vals.size == 0:
        return {}

    uniq, cnts = np.unique(vals, return_counts=True)
    out = {}
    for code, count in zip(uniq.tolist(), cnts.tolist()):
        klass = LULC_CLASS_MAP.get(int(code), "unclassified")
        out[klass] = out.get(klass, 0) + int(count)
    return out


def compute_lulc_stats(villages_4044: gpd.GeoDataFrame, tif_path: Path, tfw_path: Path, suffix: str) -> pd.DataFrame:
    transform = _read_world_file(tfw_path)
    raster = np.array(Image.open(tif_path), dtype=np.uint8)

    rows = []
    for _, row in villages_4044.iterrows():
        counts = _sample_lulc_for_geometry(row.geometry, raster, transform)
        total = sum(counts.values())
        if total <= 0:
            percentages = {f"{k}_pct_{suffix}": 0.0 for k in LULC_CLASS_ORDER}
            dominant = "unclassified"
        else:
            percentages = {
                f"{k}_pct_{suffix}": round(float(counts.get(k, 0)) * 100.0 / total, 4)
                for k in LULC_CLASS_ORDER
            }
            dominant = max(LULC_CLASS_ORDER, key=lambda k: counts.get(k, 0))
        rows.append(
            {
                "village_id": int(row.village_id),
                f"lulc_{suffix}_dominant": dominant,
                f"lulc_{suffix}_pixel_count": int(total),
                **percentages,
            }
        )
    return pd.DataFrame(rows)


def summarize_lulc_presence(lulc_df: pd.DataFrame, suffix: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for klass in LULC_CLASS_ORDER:
        col = f"{klass}_pct_{suffix}"
        if col not in lulc_df.columns:
            summary[klass] = 0
            continue
        series = pd.to_numeric(lulc_df[col], errors="coerce").fillna(0.0)
        summary[klass] = int((series > 0).sum())
    return summary


def aggregate_wells(villages_geo: gpd.GeoDataFrame) -> pd.DataFrame:
    ensure_unzipped(RAW / "GTWells_Krishna.zip", STAGING / "GTWells")
    shp = find_file(STAGING / "GTWells", "kris.shp")
    wells = gpd.read_file(shp)
    if wells.crs is None:
        wells = wells.set_crs("EPSG:4326", allow_override=True)
    wells = wells.to_crs(villages_geo.crs)
    wells = wells[["Bore_Well", "Bore_Depth", "Pump_Capac", "Irrigation", "geometry"]].copy()

    joined = gpd.sjoin(
        wells,
        villages_geo[["village_id", "geometry"]],
        how="inner",
        predicate="within",
    )
    df = pd.DataFrame(joined.drop(columns="geometry"))

    grouped = (
        df.groupby(["village_id"], dropna=False)
        .agg(
            wells_total=("Bore_Well", "count"),
            wells_working_pct=("Bore_Well", lambda s: float((s.astype(str).str.lower() == "working").mean() * 100)),
            avg_bore_depth_m=("Bore_Depth", "mean"),
            avg_pump_capacity_hp=("Pump_Capac", "mean"),
            dominant_irrigation=("Irrigation", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
        )
        .reset_index()
    )
    grouped["avg_bore_depth_m"] = grouped["avg_bore_depth_m"].fillna(0).round(2)
    grouped["avg_pump_capacity_hp"] = grouped["avg_pump_capacity_hp"].fillna(0).round(2)
    grouped["wells_working_pct"] = grouped["wells_working_pct"].fillna(0).round(2)
    return grouped


def aggregate_pumping() -> pd.DataFrame:
    df = pd.read_excel(RAW / "Pumping Data.xlsx", sheet_name="Sheet1")
    df = df.rename(
        columns={
            "S.No": "district",
            "Mandal": "mandal",
            "Village": "village",
            "No. of Functioning Wells": "functioning_wells",
            "* Estimated draft per well (ha.m)": "draft_per_well_ha_m",
        }
    )
    df["district_norm"] = df["district"].map(canonical_district)
    df["mandal_norm"] = df["mandal"].map(norm_text)
    df["village_norm"] = df["village"].map(norm_text)
    df = df[df["district_norm"].isin(ALLOWED_DISTRICTS)].copy()
    df["functioning_wells"] = pd.to_numeric(df["functioning_wells"], errors="coerce").fillna(0)
    df["draft_per_well_ha_m"] = pd.to_numeric(df["draft_per_well_ha_m"], errors="coerce").fillna(0)
    out = (
        df.groupby(["district_norm", "mandal_norm", "village_norm"], dropna=False)
        .agg(
            pumping_functioning_wells=("functioning_wells", "sum"),
            pumping_estimated_draft_ha_m=("draft_per_well_ha_m", "mean"),
        )
        .reset_index()
    )
    out["pumping_estimated_draft_ha_m"] = out["pumping_estimated_draft_ha_m"].round(4)
    return out


def _apply_pumping_fallback(villages: pd.DataFrame, pumping: pd.DataFrame) -> pd.DataFrame:
    """
    Fill missing pumping metrics using a district-agnostic village/mandal match.

    Some raw pumping sheets label villages under a different district name than the
    village boundary dataset. We keep the exact district join first, then backfill
    from the more permissive match only where the exact join produced no values.
    """
    relaxed_cols = ["mandal_norm", "village_norm", "pumping_functioning_wells", "pumping_estimated_draft_ha_m"]
    relaxed = pumping[relaxed_cols].drop_duplicates(subset=["mandal_norm", "village_norm"], keep="first")
    relaxed = relaxed.rename(
        columns={
            "pumping_functioning_wells": "pumping_functioning_wells_relaxed",
            "pumping_estimated_draft_ha_m": "pumping_estimated_draft_ha_m_relaxed",
        }
    )

    villages = villages.merge(relaxed, on=["mandal_norm", "village_norm"], how="left")
    for base_col in ["pumping_functioning_wells", "pumping_estimated_draft_ha_m"]:
        relaxed_col = f"{base_col}_relaxed"
        if relaxed_col not in villages.columns:
            continue
        villages[base_col] = pd.to_numeric(villages[base_col], errors="coerce").combine_first(
            pd.to_numeric(villages[relaxed_col], errors="coerce")
        )
        villages = villages.drop(columns=[relaxed_col])
    return villages


def export_pumping_sheet_rows() -> dict:
    df = pd.read_excel(RAW / "Pumping Data.xlsx", sheet_name="Sheet1", header=1)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(
        columns={
            "Unnamed: 0": "district",
            "Unnamed: 1": "mandal",
            "Unnamed: 2": "village",
            "Unnamed: 3": "structure_type",
            "Unnamed: 4": "functioning_wells",
            "Monsoon": "monsoon_draft_ha_m",
            "Non-Monsoon": "non_monsoon_draft_ha_m",
        }
    )

    for col in ["district", "mandal", "village", "structure_type"]:
        if col in df.columns:
            if col == "structure_type":
                df[col] = df[col].fillna("Unknown").map(canonical_name)
            else:
                df[col] = df[col].fillna("").map(canonical_name)

    for col in ["functioning_wells", "monsoon_draft_ha_m", "non_monsoon_draft_ha_m"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["district", "mandal", "village"], how="any").copy()
    df["district"] = df["district"].fillna("").astype(str).str.strip()
    df["mandal"] = df["mandal"].fillna("").astype(str).str.strip()
    df["village"] = df["village"].fillna("").astype(str).str.strip()
    df["structure_type"] = df["structure_type"].fillna("Unknown").astype(str).str.strip()
    df["district"] = df["district"].map(canonical_district)
    df = df[df["district"].isin(ALLOWED_DISTRICTS)].copy()
    df["functioning_wells"] = df["functioning_wells"].fillna(0).astype(float)
    df["monsoon_draft_ha_m"] = df["monsoon_draft_ha_m"].fillna(0).astype(float).round(4)
    df["non_monsoon_draft_ha_m"] = df["non_monsoon_draft_ha_m"].fillna(0).astype(float).round(4)

    records = df[
        [
            "district",
            "mandal",
            "village",
            "structure_type",
            "functioning_wells",
            "monsoon_draft_ha_m",
            "non_monsoon_draft_ha_m",
        ]
    ].to_dict(orient="records")
    payload = {
        "source": "Pumping Data.xlsx",
        "sheet_name": "Sheet1",
        "record_count": len(records),
        "rows": records,
    }
    out_path = ROOT / "frontend" / "src" / "constants" / "pumping_data.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _monthly_columns(columns: Iterable[object]) -> list[pd.Timestamp]:
    monthly = []
    for c in columns:
        if isinstance(c, pd.Timestamp):
            monthly.append(c)
        elif hasattr(c, "year") and hasattr(c, "month"):
            monthly.append(pd.Timestamp(c))
    return sorted(monthly)


def aggregate_water_levels() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
    df = pd.read_excel(RAW / "PzWaterLevel_2024.xlsx", sheet_name="meta-historical")
    month_cols = [c for c in _monthly_columns(df.columns) if GW_PUBLIC_START <= pd.Timestamp(c) <= GW_PUBLIC_END]
    month_labels = [pd.Timestamp(c).strftime("%Y-%m") for c in month_cols]

    df["district_norm"] = df["District"].map(canonical_district)
    df["mandal_norm"] = df["Mandal Name"].map(norm_text)
    df["village_norm"] = df["Village Name"].map(norm_text)
    df = df[df["district_norm"].isin(ALLOWED_DISTRICTS)].copy()
    df["lat"] = pd.to_numeric(df["Latitude \n(Decimal Degrees)"], errors="coerce")
    df["lon"] = pd.to_numeric(df["Longitude \n(Decimal Degrees)"], errors="coerce")

    for c in month_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    def series_full(frame: pd.DataFrame) -> list[float | None]:
        series = frame[month_cols].mean(axis=0, skipna=True)
        return [None if pd.isna(v) else round(float(v), 4) for v in series.tolist()]

    def series_tail_24(full_values: list[float | None]) -> list[float | None]:
        return full_values[-24:]

    exact_rows = []
    for (dn, mn, vn), g in df.groupby(["district_norm", "mandal_norm", "village_norm"], dropna=False):
        full_values = series_full(g)
        depth = next((float(v) for v in reversed(full_values) if v is not None and np.isfinite(v)), None)
        long_term_avg = compute_long_term_avg(full_values)
        trend_slope = compute_trend_slope(full_values)
        seasonal_variation = compute_seasonal_variation(full_values, month_labels)
        _msl_vals = g["MSL in meters"].dropna().values if "MSL in meters" in g.columns else []
        _tot_depth_vals = g["Total \nDepth \nin m"].dropna().values if "Total \nDepth \nin m" in g.columns else []

        exact_rows.append(
            {
                "district_norm": dn,
                "mandal_norm": mn,
                "village_norm": vn,
                "monthly_depths_full": full_values,
                "monthly_depths_full_dates": month_labels,
                "monthly_depths_full_pairs": series_pairs(month_labels, full_values),
                "monthly_depths": series_tail_24(full_values),
                "monthly_depths_dates": month_labels[-24:],
                "depth": depth,
                "actual_last_month": depth,
                "target_last_month": depth,
                "obs_station_count": int(len(g)),
                "obs_elevation_msl_mean": round(float(np.mean(_msl_vals)), 4) if len(_msl_vals) > 0 else None,
                "obs_total_depth_m": round(float(np.mean(_tot_depth_vals)), 4) if len(_tot_depth_vals) > 0 else None,
                "long_term_avg": long_term_avg,
                "trend_slope": trend_slope,
                "seasonal_variation": seasonal_variation,
                "available_years": available_years_from_labels(month_labels),
                "principal_aquifer_obs": mode_or_unknown(g["Principal Aquifer"]) if "Principal Aquifer" in g.columns else "Unknown",
            }
        )
    agg_exact = pd.DataFrame(exact_rows)

    dm_rows = []
    for (dn, mn), g in df.groupby(["district_norm", "mandal_norm"], dropna=False):
        full_values = series_full(g)
        _dm_vals = g[month_cols].values.flatten()
        _dm_vals = _dm_vals[~np.isnan(_dm_vals)]

        dm_rows.append(
            {
                "district_norm": dn,
                "mandal_norm": mn,
                "monthly_depths_dm_full": full_values,
                "monthly_depths_dm": series_tail_24(full_values),
                "depth_dm": round(float(np.mean(_dm_vals)), 4) if len(_dm_vals) > 0 else None,
            }
        )
    agg_dm = pd.DataFrame(dm_rows)
    return agg_exact, agg_dm, month_cols


def export_source_excel_coverage(pumping_sheet: dict) -> dict:
    pz_df = pd.read_excel(RAW / "PzWaterLevel_2024.xlsx", sheet_name="meta-historical")
    pz_df["district_norm"] = pz_df["District"].map(canonical_district)
    pz_df = pz_df[pz_df["district_norm"].isin(ALLOWED_DISTRICTS)].copy()
    pz_counts = (
        pz_df["district_norm"]
        .value_counts(dropna=False)
        .sort_index()
        .astype(int)
        .to_dict()
    )

    pumping_rows = pumping_sheet.get("rows", [])
    pumping_counts: dict[str, int] = {}
    for row in pumping_rows:
        district = canonical_district(row.get("district"))
        if district not in ALLOWED_DISTRICTS:
            continue
        pumping_counts[district] = pumping_counts.get(district, 0) + 1

    payload = {
        "generated_from": ["Pumping Data.xlsx", "PzWaterLevel_2024.xlsx"],
        "districts": sorted(ALLOWED_DISTRICTS),
        "pumping": {
            "record_count": int(sum(pumping_counts.values())),
            "district_counts": pumping_counts,
        },
        "piezometer": {
            "station_count": int(sum(pz_counts.values())),
            "district_counts": pz_counts,
        },
    }
    (FRONTEND_DATA / "source_excel_coverage.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def build() -> None:
    FRONTEND_DATA.mkdir(parents=True, exist_ok=True)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    villages_native = read_village_boundaries_native()
    villages = villages_native.to_crs("EPSG:4326")
    centroid_proj = villages.to_crs("EPSG:32644").geometry.centroid
    centroid_geo = gpd.GeoSeries(centroid_proj, crs="EPSG:32644").to_crs("EPSG:4326")
    villages["centroid_lon"] = centroid_geo.x
    villages["centroid_lat"] = centroid_geo.y
    aquifers = read_aquifers()
    geomorph = read_geomorphology()
    wells = aggregate_wells(villages)
    pumping = aggregate_pumping()
    pumping_sheet = export_pumping_sheet_rows()
    water_exact, water_dm, month_cols = aggregate_water_levels()
    source_coverage = export_source_excel_coverage(pumping_sheet)
    ensure_unzipped(RAW / "KrishnaLULC.zip", STAGING / "LULC")
    villages_lulc_proj = villages_native.to_crs("EPSG:32644")
    lulc_2011 = compute_lulc_stats(
        villages_lulc_proj,
        STAGING / "LULC" / "KrishnaOrg" / "Krishna_11.tif",
        STAGING / "LULC" / "KrishnaOrg" / "Krishna_11.tfw",
        "2011",
    )
    lulc_2021 = compute_lulc_stats(
        villages_lulc_proj,
        STAGING / "LULC" / "KrishnaOrg" / "Krishna_21.tif",
        STAGING / "LULC" / "KrishnaOrg" / "Krishna_21.tfw",
        "2021",
    )
    lulc_presence_2011 = summarize_lulc_presence(lulc_2011, "2011")
    lulc_presence_2021 = summarize_lulc_presence(lulc_2021, "2021")
    print("[LULC] non-zero village counts (2011):", lulc_presence_2011)
    print("[LULC] non-zero village counts (2021):", lulc_presence_2021)
    for required in ("flooded_vegetation", "rangeland"):
        if lulc_presence_2011.get(required, 0) == 0 and lulc_presence_2021.get(required, 0) == 0:
            print(
                f"[WARN] {required} is zero for all villages in both years. "
                "Check raster CRS/transform alignment and class mapping."
            )

    villages["district_norm"] = villages["district"].map(canonical_district)
    villages["mandal_norm"] = villages["mandal"].map(norm_text)
    villages["village_norm"] = villages["village_name"].map(norm_text)
    villages["join_key"] = villages.apply(
        lambda row: build_join_key(row.get("district"), row.get("mandal"), row.get("village_name")),
        axis=1,
    )

    # Join aquifer by centroid.
    centroids = villages[["village_id", "geometry"]].to_crs("EPSG:32644").copy()
    centroids["geometry"] = centroids.geometry.centroid
    centroids = gpd.GeoDataFrame(centroids, geometry="geometry", crs="EPSG:32644").to_crs(villages.crs)
    aq_join = gpd.sjoin(centroids, aquifers[["AQUI_CODE", "Geo_Class", "geometry"]], how="left", predicate="within")
    aq_join = aq_join[["village_id", "AQUI_CODE", "Geo_Class"]].rename(
        columns={"AQUI_CODE": "aquifer_code", "Geo_Class": "aquifer_class"}
    )
    villages = villages.merge(aq_join, on="village_id", how="left")
    villages["aquifer_code"] = villages["aquifer_code"].fillna("NA")
    villages["aquifer_class"] = villages["aquifer_class"].fillna("Unknown")

    # Join geomorphology by centroid.
    gm_join = gpd.sjoin(centroids, geomorph, how="left", predicate="within")[["village_id", "geomorphology"]]
    villages = villages.merge(gm_join, on="village_id", how="left")
    villages["geomorphology"] = villages["geomorphology"].fillna("Unknown")

    # Tabular joins.
    villages = villages.merge(wells, on=["village_id"], how="left")
    villages = villages.merge(pumping, on=["district_norm", "mandal_norm", "village_norm"], how="left")
    villages = _apply_pumping_fallback(villages, pumping)
    villages = villages.merge(water_exact, on=["district_norm", "mandal_norm", "village_norm"], how="left")
    villages = villages.merge(water_dm, on=["district_norm", "mandal_norm"], how="left")
    villages = villages.merge(lulc_2011, on="village_id", how="left")
    villages = villages.merge(lulc_2021, on="village_id", how="left")

    villages["monthly_depths"] = villages["monthly_depths"].where(villages["monthly_depths"].notna(), villages["monthly_depths_dm"])
    villages["monthly_depths"] = villages["monthly_depths"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    villages["monthly_depths_full"] = villages["monthly_depths_full"].where(villages["monthly_depths_full"].notna(), villages["monthly_depths_dm_full"])
    villages["monthly_depths_full"] = villages["monthly_depths_full"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    villages["depth"] = pd.to_numeric(villages["depth"], errors="coerce")
    villages["depth"] = villages["depth"].fillna(pd.to_numeric(villages["depth_dm"], errors="coerce")).round(2)

    for c, default in [
        ("wells_total", 0),
        ("wells_working_pct", 0.0),
        ("avg_bore_depth_m", 0.0),
        ("avg_pump_capacity_hp", 0.0),
        ("pumping_functioning_wells", 0),
        ("pumping_estimated_draft_ha_m", 0.0),
        ("obs_station_count", 0),
    ]:
        villages[c] = pd.to_numeric(villages[c], errors="coerce").fillna(default)

    villages["dominant_irrigation"] = villages["dominant_irrigation"].fillna("Unknown")
    villages["weathered_rock"] = 12
    villages["fractured_rock"] = 18
    for col in [f"lulc_2011_dominant", f"lulc_2021_dominant"]:
        villages[col] = villages[col].fillna("unclassified")
    for col in [f"lulc_2011_pixel_count", f"lulc_2021_pixel_count"]:
        villages[col] = pd.to_numeric(villages[col], errors="coerce").fillna(0).astype(int)
    for klass in LULC_CLASS_ORDER:
        for year in ["2011", "2021"]:
            col = f"{klass}_pct_{year}"
            villages[col] = pd.to_numeric(villages[col], errors="coerce").fillna(0.0).round(4)
    villages["lulc_change"] = np.where(
        villages["lulc_2011_dominant"] == villages["lulc_2021_dominant"],
        "stable",
        villages["lulc_2011_dominant"] + "_to_" + villages["lulc_2021_dominant"],
    )

    # Keep compatibility columns consumed by backend service and UI summaries (use 2021 snapshot).
    villages["water_pct"] = villages["water_pct_2021"]
    villages["trees_pct"] = villages["trees_pct_2021"]
    villages["flooded_vegetation_pct"] = villages["flooded_vegetation_pct_2021"]
    villages["crops_pct"] = villages["crops_pct_2021"]
    villages["built_area_pct"] = villages["built_area_pct_2021"]
    villages["bare_ground_pct"] = villages["bare_ground_pct_2021"]
    villages["rangeland_pct"] = villages["rangeland_pct_2021"]
    villages["snow_ice_pct"] = villages["snow_ice_pct_2021"]
    villages["clouds_pct"] = villages["clouds_pct_2021"]

    # Frontend boundary datasets.
    village_cols = [
        "village_id",
        "village_name",
        "district",
        "mandal",
        "state",
        "depth",
        "monthly_depths",
        "monthly_depths_full",
        "monthly_depths_dates",
        "monthly_depths_full_dates",
        "available_years",
        "weathered_rock",
        "fractured_rock",
        "aquifer_code",
        "aquifer_class",
        "geomorphology",
        "wells_total",
        "wells_working_pct",
        "avg_bore_depth_m",
        "avg_pump_capacity_hp",
        "dominant_irrigation",
        "pumping_functioning_wells",
        "pumping_estimated_draft_ha_m",
        "obs_station_count",
        "actual_last_month",
        "target_last_month",
        "long_term_avg",
        "trend_slope",
        "seasonal_variation",
        "obs_elevation_msl_mean",
        "obs_total_depth_m",
        "lulc_2011_dominant",
        "lulc_2021_dominant",
        "lulc_change",
        "lulc_2011_pixel_count",
        "lulc_2021_pixel_count",
        "water_pct",
        "trees_pct",
        "flooded_vegetation_pct",
        "crops_pct",
        "built_area_pct",
        "bare_ground_pct",
        "rangeland_pct",
        "snow_ice_pct",
        "clouds_pct",
        "water_pct_2011",
        "trees_pct_2011",
        "flooded_vegetation_pct_2011",
        "crops_pct_2011",
        "built_area_pct_2011",
        "bare_ground_pct_2011",
        "snow_ice_pct_2011",
        "clouds_pct_2011",
        "rangeland_pct_2011",
        "water_pct_2021",
        "trees_pct_2021",
        "flooded_vegetation_pct_2021",
        "crops_pct_2021",
        "built_area_pct_2021",
        "bare_ground_pct_2021",
        "snow_ice_pct_2021",
        "clouds_pct_2021",
        "rangeland_pct_2021",
        "centroid_lat",
        "centroid_lon",
        "geometry",
    ]
    village_front = villages[village_cols].copy()
    village_front.to_file(FRONTEND_DATA / "village_boundaries.geojson", driver="GeoJSON")
    village_front.to_file(FRONTEND_DATA / "villages.geojson", driver="GeoJSON")

    # Aquifer dataset for frontend.
    aquifers_out = aquifers.copy()
    aquifers_out.to_file(FRONTEND_DATA / "aquifers_krishna.geojson", driver="GeoJSON")

    # Sidebar hierarchy based strictly on village boundaries.
    districts = []
    for district_name, district_df in village_front.sort_values(["district", "mandal", "village_name"]).groupby("district"):
        mandals = []
        for mandal_name, mandal_df in district_df.groupby("mandal"):
            mandals.append(
                {
                    "name": mandal_name,
                    "villages": sorted(set(mandal_df["village_name"].astype(str).tolist())),
                }
            )
        districts.append({"name": district_name, "mandals": mandals})
    available_village_zips = [
        source["zip"] for source in VILLAGE_BOUNDARY_SOURCES if (RAW / source["zip"]).exists()
    ]
    excel_locations = {
        "generated_from": [
            *available_village_zips,
            "GTWells_Krishna.zip",
            "Pumping Data.xlsx",
            "PzWaterLevel_2024.xlsx",
        ],
        "district_count": len(districts),
        "districts": districts,
        "pumping_record_count": pumping_sheet["record_count"],
        "source_excel_coverage": source_coverage,
    }
    (FRONTEND_DATA / "excel_locations.json").write_text(json.dumps(excel_locations, ensure_ascii=False, indent=2), encoding="utf-8")

    # Export files used by analysis workflows.
    village_front.to_file(EXPORTS / "map_data.geojson", driver="GeoJSON")
    table_cols = [c for c in village_cols if c != "geometry"] + ["district_norm", "mandal_norm", "village_norm"]
    villages[table_cols].to_csv(OUTPUT / "final_dataset.csv", index=False)

    print("Built authoritative datasets")
    print(f"villages: {len(village_front)}")
    print(f"districts: {len(districts)}")
    print(f"aquifer polygons: {len(aquifers_out)}")


if __name__ == "__main__":
    build()
