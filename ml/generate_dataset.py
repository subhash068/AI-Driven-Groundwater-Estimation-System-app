import argparse
import json
import os
import re
import zipfile
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image
import requests
from shapely import contains_xy
from shapely.geometry import Point

try:
    import rasterio
    from rasterio.mask import mask as raster_mask
except ImportError:  # pragma: no cover
    rasterio = None
    raster_mask = None

Image.MAX_IMAGE_PIXELS = None


DEFAULT_CRS = "EPSG:4326"
AREA_CRS = "EPSG:32644"

# Exact legend mapping provided by user.
LULC_COLOR_MAP = {
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

# Optional 1-band categorical fallback.
LULC_CODE_MAP = {
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

NOISE_CLASSES = {"Clouds", "Snow/Ice"}
ALL_LULC_CLASSES = list(LULC_COLOR_MAP.keys())
OUTPUT_CLASSES = ["Water", "Trees", "Crops", "Built Area", "Bare Ground", "Rangeland"]
GW_PUBLIC_START = pd.Timestamp("1998-01-01")
GW_PUBLIC_END = pd.Timestamp("2024-12-01")


def normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def series_or_default(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column in frame.columns:
        return safe_numeric(frame[column]).fillna(default)
    return pd.Series(default, index=frame.index, dtype=float)


def aquifer_storage_factor_from_type(value: object) -> float:
    text = normalize_text(value)
    if not text or text == "unknown":
        return 1.0

    high_storage_terms = (
        "alluvium",
        "alluvial",
        "valley fill",
        "sandstone",
        "limestone",
        "shale",
        "unconsolidated",
    )
    medium_storage_terms = (
        "laterite",
        "pediment",
        "weathered",
    )
    low_storage_terms = (
        "granite",
        "gneiss",
        "charnokite",
        "basalt",
        "quartzite",
        "schist",
        "khondalite",
    )

    if any(term in text for term in high_storage_terms):
        return 1.35
    if any(term in text for term in medium_storage_terms):
        return 1.1
    if any(term in text for term in low_storage_terms):
        return 0.7
    return 1.0


def find_shapefile_in_zip(zip_path: Path, name_hint: str | None = None) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        shp_files = [n for n in zf.namelist() if n.lower().endswith(".shp")]
    if not shp_files:
        raise FileNotFoundError(f"No .shp file found inside {zip_path}")
    if name_hint:
        hinted = [n for n in shp_files if name_hint.lower() in n.lower()]
        if hinted:
            return hinted[0]
    return shp_files[0]


def read_shapefile_from_zip(zip_path: Path, name_hint: str | None = None) -> gpd.GeoDataFrame:
    shp_inside = find_shapefile_in_zip(zip_path, name_hint=name_hint)
    gdf = gpd.read_file(f"zip://{zip_path}!{shp_inside}")
    if gdf.crs is None:
        gdf = gdf.set_crs(DEFAULT_CRS)
    return gdf.to_crs(DEFAULT_CRS)


def extract_files_from_zip(
    zip_path: Path,
    dest_dir: Path,
    suffixes: tuple[str, ...],
    name_hint: str | None = None,
) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            n for n in zf.namelist()
            if n.lower().endswith(suffixes)
            and (name_hint is None or name_hint.lower() in Path(n).name.lower())
        ]
        for member in members:
            out_file = dest_dir / Path(member).name
            if not out_file.exists():
                out_file.write_bytes(zf.read(member))
            extracted.append(out_file)
    return extracted


def extract_named_file_from_zip(zip_path: Path, dest_dir: Path, file_name: str) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        matches = [n for n in zf.namelist() if Path(n).name.lower() == file_name.lower()]
        if not matches:
            return None
        member = matches[0]
        out_file = dest_dir / Path(member).name
        if not out_file.exists():
            out_file.write_bytes(zf.read(member))
        return out_file


def resolve_lulc_raster_pairs(lulc_zip: Path) -> list[tuple[Path, Path]]:
    candidates: list[tuple[Path, Path]] = []
    probable_dirs = [
        Path("data/_staging/LULC/KrishnaOrg"),
        Path("data/processed/lulc_rasters"),
        Path("data/processed/lulc_extract"),
    ]
    seen_names: set[str] = set()
    for directory in probable_dirs:
        if not directory.exists():
            continue
        for tif_path in sorted(directory.glob("*.tif")):
            tfw_path = tif_path.with_suffix(".tfw")
            if tfw_path.exists():
                key = tif_path.name.lower()
                if key in seen_names:
                    continue
                try:
                    with Image.open(tif_path) as img:
                        img.verify()
                except Exception:
                    continue
                candidates.append((tif_path, tfw_path))
                seen_names.add(key)

    if candidates:
        return candidates

    extract_dir = Path("data/processed/lulc_extract")
    raster_paths = extract_files_from_zip(lulc_zip, extract_dir, (".tif", ".tiff"))
    pairs: list[tuple[Path, Path]] = []
    for raster_path in sorted(raster_paths):
        tfw_path = extract_named_file_from_zip(lulc_zip, extract_dir, raster_path.with_suffix(".tfw").name)
        if tfw_path is not None:
            pairs.append((raster_path, tfw_path))
    return pairs


def compute_bbox_wgs84(villages: gpd.GeoDataFrame, padding_deg: float = 0.02) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = villages.to_crs(DEFAULT_CRS).total_bounds
    return (
        float(minx - padding_deg),
        float(miny - padding_deg),
        float(maxx + padding_deg),
        float(maxy + padding_deg),
    )


def resolve_dem_raster(data_dir: Path, villages: gpd.GeoDataFrame) -> tuple[Path | None, str]:
    candidate_patterns = [
        "*.tif",
        "*.tiff",
        "*.img",
        "*.asc",
        "*.bil",
    ]
    candidate_dirs = [data_dir, data_dir / "external", Path("data/processed"), Path("data/processed/dem"), Path("data/processed/dem_extract")]
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        for pattern in candidate_patterns:
            matches = sorted(directory.rglob(pattern))
            for match in matches:
                name_lower = match.name.lower()
                if not any(token in name_lower for token in ("srtm", "nasadem", "dem")) and directory.name.lower() not in {"dem", "dem_extract"}:
                    continue
                return match, match.name

    api_key = (
        os.getenv("OPENTOPO_API_KEY")
        or os.getenv("OPEN_TOPOGRAPHY_API_KEY")
        or os.getenv("OT_API_KEY")
    )
    if not api_key:
        return None, "missing_dem_raster"

    dem_dir = data_dir / "external"
    dem_dir.mkdir(parents=True, exist_ok=True)
    dem_path = dem_dir / "krishna_srtm_gl1.tif"
    if dem_path.exists():
        return dem_path, "SRTM"

    west, south, east, north = compute_bbox_wgs84(villages)
    params = {
        "demtype": "SRTMGL1",
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    url = "https://portal.opentopography.org/API/globaldem"
    try:
        print(
            f"[DEM] Downloading SRTM GL1 clip for Krishna extent: "
            f"west={west:.4f}, south={south:.4f}, east={east:.4f}, north={north:.4f}"
        )
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
    except Exception as exc:
        warnings.warn(f"DEM download failed from OpenTopography: {exc}", RuntimeWarning)
        return None, "dem_download_failed"

    dem_path.write_bytes(response.content)
    print(f"[DEM] Saved DEM raster to {dem_path}")
    return dem_path, "SRTM"


def pick_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {str(col).strip().lower(): col for col in columns}
    for candidate in candidates:
        for key, original in lowered.items():
            if candidate in key:
                return original
    return None


def mode_or_unknown(values: pd.Series, default: str = "Unknown") -> str:
    cleaned = values.dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]
    if cleaned.empty:
        return default
    return str(cleaned.mode().iloc[0]).strip()


def serialize_monthly_values(values: pd.Series | list | tuple) -> list[float | None]:
    out: list[float | None] = []
    for value in values:
        if pd.isna(value):
            out.append(None)
        else:
            out.append(round(float(value), 4))
    return out


def parse_month_label(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m")


def parse_month_timestamp(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).to_period("M").to_timestamp()


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
    if not np.isfinite(slope):
        return None
    return round(float(slope), 6)


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
    if not np.isfinite(seasonal):
        return None
    return round(seasonal, 4)


def available_years_from_labels(labels: list[str]) -> list[int]:
    years = {
        int(label[:4])
        for label in labels
        if isinstance(label, str) and len(label) >= 4 and label[:4].isdigit()
    }
    return sorted(years)


def last_finite(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is None:
            continue
        numeric = float(value)
        if np.isfinite(numeric):
            return round(numeric, 4)
    return None


def dominant_polygon_overlay(
    villages: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    value_columns: list[str],
) -> pd.DataFrame:
    village_cols = ["Village_ID", "geometry"]
    polygons = polygons[[*value_columns, "geometry"]].copy()
    villages_area = villages[village_cols].to_crs(AREA_CRS)
    polygons_area = polygons.to_crs(AREA_CRS)
    inter = gpd.overlay(villages_area, polygons_area, how="intersection", keep_geom_type=False)
    inter = inter[inter.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if inter.empty:
        return pd.DataFrame(columns=["Village_ID", *value_columns])
    inter["_area"] = inter.geometry.area
    dominant = inter.sort_values("_area", ascending=False).drop_duplicates("Village_ID")
    return pd.DataFrame(dominant[["Village_ID", *value_columns]])


def closest_lulc_class(rgb: tuple[int, int, int]) -> str:
    best_class = "Bare Ground"
    best_dist = float("inf")
    for lulc_class, color in LULC_COLOR_MAP.items():
        dist = (
            (rgb[0] - color[0]) ** 2
            + (rgb[1] - color[1]) ** 2
            + (rgb[2] - color[2]) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best_class = lulc_class
    return best_class


def load_villages(village_zip: Path) -> gpd.GeoDataFrame:
    villages = read_shapefile_from_zip(village_zip, name_hint="OKri_Vil")
    villages = villages.rename(columns={c: c.strip() for c in villages.columns})

    village_name_col = "DVNAME" if "DVNAME" in villages.columns else "Village_Name"
    villages["Village_Name"] = villages[village_name_col].astype(str).str.strip()
    villages["Village_ID"] = np.arange(1, len(villages) + 1)
    villages["Village_Name_Norm"] = villages["Village_Name"].map(normalize_text)
    villages["District"] = villages.get("DNAME", "Unknown").astype(str).str.strip()
    villages["Mandal"] = villages.get("DMNAME", "Unknown").astype(str).str.strip()
    villages["State"] = "Andhra Pradesh"
    villages["Village_Latitude"] = safe_numeric(villages.get("latitude", pd.Series(index=villages.index)))
    villages["Village_Longitude"] = safe_numeric(villages.get("longitude", pd.Series(index=villages.index)))
    return villages.to_crs(DEFAULT_CRS)


def _extract_year(path: Path) -> int | None:
    match = re.search(r"(20\d{2})", path.stem)
    if match:
        return int(match.group(1))
    match = re.search(r"[_-](\d{2})$", path.stem)
    if match:
        return 2000 + int(match.group(1))
    return None


def _tfw_to_transform(tfw_path: Path) -> tuple[float, float, float, float, float, float]:
    lines = [float(line.strip()) for line in tfw_path.read_text().splitlines() if line.strip()]
    if len(lines) != 6:
        raise ValueError(f"Unexpected TFW format in {tfw_path}")
    return tuple(lines)  # A, D, B, E, C, F


def _pixel_window(bounds: tuple[float, float, float, float], transform: tuple[float, float, float, float, float, float], width: int, height: int) -> tuple[int, int, int, int] | None:
    a, _, _, e, c, f = transform
    minx, miny, maxx, maxy = bounds
    if abs(a) < 1e-12 or abs(e) < 1e-12:
        return None

    left = int(np.floor((minx - c) / a))
    right = int(np.ceil((maxx - c) / a))
    top = int(np.floor((maxy - f) / e))
    bottom = int(np.ceil((miny - f) / e))

    x0 = max(0, min(left, right))
    x1 = min(width, max(left, right))
    y0 = max(0, min(top, bottom))
    y1 = min(height, max(top, bottom))
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, x1, y1


def _class_counts_from_pillow(raster_path: Path, tfw_path: Path, villages: gpd.GeoDataFrame) -> pd.DataFrame:
    img = Image.open(raster_path)
    transform = _tfw_to_transform(tfw_path)
    a, _, _, e, c, f = transform
    arr = np.array(img)
    palette = img.getpalette() or []

    unique_codes = np.unique(arr)
    code_to_class: dict[int, str] = {}
    for code in unique_codes:
        if int(code) == 255:
            continue
        start = int(code) * 3
        if start + 2 >= len(palette):
            continue
        sample_rgb = tuple(int(v) for v in palette[start:start + 3])
        code_to_class[int(code)] = closest_lulc_class(sample_rgb)

    rows: list[dict] = []
    for _, village in villages.iterrows():
        row = {"Village_ID": int(village["Village_ID"])}
        for klass in ALL_LULC_CLASSES:
            row[f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct"] = 0.0

        window = _pixel_window(village.geometry.bounds, transform, img.width, img.height)
        if window is None:
            rows.append(row)
            continue

        x0, y0, x1, y1 = window
        crop_codes = arr[y0:y1, x0:x1]
        if crop_codes.size == 0:
            rows.append(row)
            continue

        xs = c + (np.arange(x0, x1) * a)
        ys = f + (np.arange(y0, y1) * e)
        xx, yy = np.meshgrid(xs, ys)
        mask = contains_xy(village.geometry, xx, yy)
        if mask.sum() == 0:
            rows.append(row)
            continue

        masked_codes = crop_codes[mask]
        counts = {klass: 0 for klass in ALL_LULC_CLASSES}
        valid_codes, freq = np.unique(masked_codes, return_counts=True)
        for code, count in zip(valid_codes, freq):
            code_int = int(code)
            if code_int == 255:
                continue
            klass = code_to_class.get(code_int)
            if klass:
                counts[klass] += int(count)

        clean_total = sum(v for k, v in counts.items() if k not in NOISE_CLASSES)
        if clean_total > 0:
            for klass in ALL_LULC_CLASSES:
                row[f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct"] = (
                    counts[klass] / clean_total * 100.0
                )
        rows.append(row)

    return pd.DataFrame(rows)


def _class_counts_from_raster(src, geom: dict) -> dict[str, int]:
    counts = {klass: 0 for klass in ALL_LULC_CLASSES}
    clipped, _ = raster_mask(src, [geom], crop=True, filled=False)
    if clipped.size == 0:
        return counts

    if src.count >= 3:
        valid = ~clipped[0].mask
        if valid.sum() == 0:
            return counts
        r = np.asarray(clipped[0].data[valid], dtype=np.uint8)
        g = np.asarray(clipped[1].data[valid], dtype=np.uint8)
        b = np.asarray(clipped[2].data[valid], dtype=np.uint8)
        rgb_stack = np.stack([r, g, b], axis=1)
        unique_colors, freq = np.unique(rgb_stack, axis=0, return_counts=True)
        for rgb, count in zip(unique_colors, freq):
            klass = closest_lulc_class((int(rgb[0]), int(rgb[1]), int(rgb[2])))
            counts[klass] += int(count)
        return counts

    band = np.asarray(clipped[0].filled(np.nan), dtype=float)
    valid_vals = band[np.isfinite(band)]
    if valid_vals.size == 0:
        return counts
    unique_codes, freq = np.unique(valid_vals.astype(int), return_counts=True)
    for code, count in zip(unique_codes, freq):
        klass = LULC_CODE_MAP.get(int(code))
        if klass:
            counts[klass] += int(count)
    return counts


def extract_lulc_percentages(villages: gpd.GeoDataFrame, lulc_zip: Path) -> pd.DataFrame:
    raster_pairs = resolve_lulc_raster_pairs(lulc_zip)
    if not raster_pairs:
        raise FileNotFoundError(f"No .tif file found inside {lulc_zip}")

    year_frames: list[pd.DataFrame] = []
    for raster_path, tfw_path in sorted(raster_pairs, key=lambda pair: pair[0].name):
        year = _extract_year(raster_path)
        if rasterio is not None and raster_mask is not None:
            print(f"[LULC] Using real raster processing via rasterio for {raster_path.name}")
            with rasterio.open(raster_path) as src:
                villages_proj = villages[["Village_ID", "geometry"]].to_crs(src.crs or DEFAULT_CRS)
                rows = []
                for _, village in villages_proj.iterrows():
                    counts = _class_counts_from_raster(src, village.geometry.__geo_interface__)
                    clean_total = sum(v for k, v in counts.items() if k not in NOISE_CLASSES)
                    row = {"Village_ID": int(village["Village_ID"]), "year": year}
                    for klass in ALL_LULC_CLASSES:
                        key = f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct"
                        row[key] = (counts[klass] / clean_total * 100.0) if clean_total > 0 else 0.0
                    rows.append(row)
                year_frames.append(pd.DataFrame(rows))
            continue

        if tfw_path is not None:
            print(f"[LULC] Using real raster processing via Pillow+TFW for {raster_path.name}")
            villages_proj = villages[["Village_ID", "geometry"]].to_crs(AREA_CRS)
            frame = _class_counts_from_pillow(raster_path, tfw_path, villages_proj)
            frame["year"] = year
            year_frames.append(frame)
            continue

        warnings.warn(
            f"[LULC] WARNING: No raster backend available for {raster_path.name}; synthetic fallback is being used.",
            RuntimeWarning,
        )
        rng = np.random.default_rng(42)
        rows = []
        for village_id in villages["Village_ID"]:
            parts = rng.dirichlet(np.ones(len(OUTPUT_CLASSES))) * 100.0
            row = {"Village_ID": int(village_id), "year": year}
            for klass, value in zip(OUTPUT_CLASSES, parts):
                key = f"{klass.lower().replace(' ', '_').replace('/', '_')}_pct"
                row[key] = round(float(value), 4)
            row["flooded_vegetation_pct"] = 0.0
            row["snow_ice_pct"] = 0.0
            row["clouds_pct"] = 0.0
            rows.append(row)
        year_frames.append(pd.DataFrame(rows))

    if not year_frames:
        return pd.DataFrame({"Village_ID": villages["Village_ID"]})

    combined = pd.concat(year_frames, ignore_index=True)
    if combined["year"].notna().any():
        latest_year = int(combined["year"].dropna().max())
    else:
        latest_year = 0

    latest = combined[combined["year"] == latest_year].copy() if latest_year else combined.copy()
    latest = latest.drop(columns=["year"], errors="ignore")
    latest = latest.rename(
        columns={
            "water_pct": "Water%",
            "trees_pct": "Trees%",
            "crops_pct": "Crops%",
            "built_area_pct": "Built%",
            "bare_ground_pct": "Bare%",
            "rangeland_pct": "Rangeland%",
        }
    )
    latest["lulc_latest_year"] = latest_year if latest_year else np.nan

    result = latest.copy()
    year_values = sorted(y for y in combined["year"].dropna().unique())
    for year in year_values:
        year_df = combined[combined["year"] == year][["Village_ID", *[c for c in combined.columns if c.endswith("_pct")]]].copy()
        rename_map = {
            col: f"{col.replace('_pct', '').replace('built_area', 'built').replace('bare_ground', 'bare').replace('flooded_vegetation', 'flooded_vegetation').replace('snow_ice', 'snow_ice').replace('rangeland', 'rangeland')}_{int(year)}%"
            for col in year_df.columns if col != "Village_ID"
        }
        year_df = year_df.rename(columns=rename_map)
        result = result.merge(year_df, on="Village_ID", how="left")

    # Add year-aware dominant class and built-area change when at least two snapshots exist.
    if len(year_values) >= 2:
        start_year = int(year_values[0])
        end_year = int(year_values[-1])
        start_cols = {
            "Water": f"water_{start_year}%",
            "Trees": f"trees_{start_year}%",
            "Flooded Vegetation": f"flooded_vegetation_{start_year}%",
            "Crops": f"crops_{start_year}%",
            "Built Area": f"built_{start_year}%",
            "Bare Ground": f"bare_{start_year}%",
            "Snow/Ice": f"snow_ice_{start_year}%",
            "Clouds": f"clouds_{start_year}%",
            "Rangeland": f"rangeland_{start_year}%",
        }
        end_cols = {
            "Water": f"water_{end_year}%",
            "Trees": f"trees_{end_year}%",
            "Flooded Vegetation": f"flooded_vegetation_{end_year}%",
            "Crops": f"crops_{end_year}%",
            "Built Area": f"built_{end_year}%",
            "Bare Ground": f"bare_{end_year}%",
            "Snow/Ice": f"snow_ice_{end_year}%",
            "Clouds": f"clouds_{end_year}%",
            "Rangeland": f"rangeland_{end_year}%",
        }

        def dominant_class(row: pd.Series, mapping: dict[str, str]) -> str:
            scored = [(klass, float(row.get(col, 0.0) or 0.0)) for klass, col in mapping.items()]
            scored.sort(key=lambda item: item[1], reverse=True)
            label = scored[0][0] if scored else "Unknown"
            return normalize_text(label) or "unknown"

        result["lulc_start_year"] = start_year
        result["lulc_end_year"] = end_year
        result["lulc_start_dominant"] = result.apply(lambda row: dominant_class(row, start_cols), axis=1)
        result["lulc_end_dominant"] = result.apply(lambda row: dominant_class(row, end_cols), axis=1)
        result["built_area_change_pct"] = safe_numeric(result.get(end_cols["Built Area"], 0.0)).fillna(0.0) - safe_numeric(
            result.get(start_cols["Built Area"], 0.0)
        ).fillna(0.0)
    else:
        result["lulc_start_year"] = np.nan
        result["lulc_end_year"] = np.nan
        result["lulc_start_dominant"] = "unknown"
        result["lulc_end_dominant"] = "unknown"
        result["built_area_change_pct"] = 0.0

    return result


def extract_soil_by_village(villages: gpd.GeoDataFrame, village_zip: Path) -> pd.DataFrame:
    soils = read_shapefile_from_zip(village_zip, name_hint="OKri_Soils")
    soils = soils.rename(columns={c: c.strip() for c in soils.columns})
    soil_col = "DESCRIPTIO" if "DESCRIPTIO" in soils.columns else soils.columns[0]
    soils["Soil"] = soils[soil_col].astype(str).str.strip()
    soils["Soil_Taxonomy"] = soils.get("SOIL_TAXON", "Unknown").astype(str).str.strip()
    soils["Soil_Map_Unit"] = soils.get("MAPPING_UN", "Unknown").astype(str).str.strip()

    out = dominant_polygon_overlay(villages, soils, ["Soil", "Soil_Taxonomy", "Soil_Map_Unit"])
    if out.empty:
        return pd.DataFrame(
            {
                "Village_ID": villages["Village_ID"],
                "Soil": "Unknown",
                "Soil_Taxonomy": "Unknown",
                "Soil_Map_Unit": "Unknown",
            }
        )
    return out


def extract_aquifer_by_village(villages: gpd.GeoDataFrame, aquifer_zip: Path) -> pd.DataFrame:
    aquifers = read_shapefile_from_zip(aquifer_zip)
    aquifers = aquifers.rename(columns={c: c.strip() for c in aquifers.columns})
    aquifers["aquifer_code"] = aquifers.get("AQUI_CODE", "Unknown").astype(str).str.strip()
    aquifers["aquifer_type"] = aquifers.get("Geo_Class", "Unknown").astype(str).str.strip()
    out = dominant_polygon_overlay(villages, aquifers, ["aquifer_code", "aquifer_type"])
    if out.empty:
        return pd.DataFrame({"Village_ID": villages["Village_ID"], "aquifer_code": "Unknown", "aquifer_type": "Unknown"})
    return out


def extract_geomorphology_by_village(villages: gpd.GeoDataFrame, gm_zip: Path) -> pd.DataFrame:
    gm = read_shapefile_from_zip(gm_zip)
    gm = gm.rename(columns={c: c.strip() for c in gm.columns})
    geom_col = pick_column(list(gm.columns), ["fin_desc", "new_descri", "discriptio", "discript_1"])
    if geom_col is None:
        return pd.DataFrame({"Village_ID": villages["Village_ID"], "geomorphology": "Unknown"})
    gm["geomorphology"] = gm[geom_col].astype(str).str.strip()
    out = dominant_polygon_overlay(villages, gm, ["geomorphology"])
    if out.empty:
        return pd.DataFrame({"Village_ID": villages["Village_ID"], "geomorphology": "Unknown"})
    return out


def extract_gtwell_features(villages: gpd.GeoDataFrame, wells_zip: Path) -> pd.DataFrame:
    wells = read_shapefile_from_zip(wells_zip)
    wells = wells.rename(columns={c: c.strip() for c in wells.columns})

    lat_col = pick_column(list(wells.columns), ["lat"])
    lon_col = pick_column(list(wells.columns), ["long"])
    village_col = pick_column(list(wells.columns), ["village_na"])
    if lat_col and lon_col:
        wells[lat_col] = safe_numeric(wells[lat_col])
        wells[lon_col] = safe_numeric(wells[lon_col])
        wells = wells.dropna(subset=[lat_col, lon_col]).copy()
        wells = gpd.GeoDataFrame(
            wells.drop(columns=["geometry"], errors="ignore"),
            geometry=gpd.points_from_xy(wells[lon_col], wells[lat_col]),
            crs=DEFAULT_CRS,
        )
    else:
        wells = wells.to_crs(DEFAULT_CRS)

    joined = gpd.sjoin(
        wells,
        villages[["Village_ID", "Village_Name_Norm", "geometry"]],
        how="left",
        predicate="within",
    )

    if village_col is not None:
        unmatched = joined["Village_ID"].isna()
        lookup = villages.drop_duplicates("Village_Name_Norm").set_index("Village_Name_Norm")["Village_ID"].to_dict()
        joined.loc[unmatched, "Village_ID"] = joined.loc[unmatched, village_col].map(normalize_text).map(lookup)

    joined["Village_ID"] = safe_numeric(joined["Village_ID"])
    joined = joined.dropna(subset=["Village_ID"]).copy()
    joined["Village_ID"] = joined["Village_ID"].astype(int)

    joined["Bore_Depth"] = safe_numeric(joined.get("Bore_Depth", pd.Series(index=joined.index)))
    joined["Pump_Capac"] = safe_numeric(joined.get("Pump_Capac", pd.Series(index=joined.index)))
    joined["Extant_Lan"] = safe_numeric(joined.get("Extant_Lan", pd.Series(index=joined.index)))
    joined["is_working"] = joined.get("Bore_Well", "").astype(str).str.contains("working", case=False, na=False).astype(float)

    agg = joined.groupby("Village_ID", as_index=False).agg(
        wells_total=("Village_ID", "size"),
        wells_working_pct=("is_working", "mean"),
        avg_bore_depth_m=("Bore_Depth", "mean"),
        avg_pump_capacity_hp=("Pump_Capac", "mean"),
        avg_extant_land_hac=("Extant_Lan", "mean"),
        dominant_irrigation=("Irrigation", lambda s: mode_or_unknown(s)),
        dominant_crop_type=("Crop_Type", lambda s: mode_or_unknown(s)),
        dominant_well_type=("Well_Type", lambda s: mode_or_unknown(s)),
    )
    agg["wells_working_pct"] = agg["wells_working_pct"].fillna(0.0) * 100.0
    return agg


def extract_tank_features(villages: gpd.GeoDataFrame, village_zip: Path) -> pd.DataFrame:
    tanks = read_shapefile_from_zip(village_zip, name_hint="OKri_MIT")
    tanks = tanks.rename(columns={c: c.strip() for c in tanks.columns})
    tanks = tanks[tanks.geometry.notna()].copy()
    if tanks.empty:
        return pd.DataFrame(
            {
                "Village_ID": villages["Village_ID"],
                "tank_count": 0,
                "distance_to_nearest_tank_km": np.nan,
            }
        )

    joined = gpd.sjoin(
        tanks[["geometry"]],
        villages[["Village_ID", "geometry"]],
        how="left",
        predicate="within",
    )
    counts = joined.groupby("Village_ID", as_index=False).size().rename(columns={"size": "tank_count"})

    village_centroids = villages[["Village_ID", "geometry"]].to_crs(AREA_CRS).copy()
    village_centroids["geometry"] = village_centroids.geometry.centroid
    tanks_area = tanks.to_crs(AREA_CRS)
    nearest = gpd.sjoin_nearest(
        village_centroids,
        tanks_area[["geometry"]],
        how="left",
        distance_col="distance_m",
    )
    nearest = pd.DataFrame(nearest[["Village_ID", "distance_m"]]).drop_duplicates("Village_ID")
    nearest["distance_to_nearest_tank_km"] = nearest["distance_m"] / 1000.0
    out = villages[["Village_ID"]].merge(counts, on="Village_ID", how="left").merge(
        nearest[["Village_ID", "distance_to_nearest_tank_km"]],
        on="Village_ID",
        how="left",
    )
    out["tank_count"] = safe_numeric(out["tank_count"]).fillna(0).astype(int)
    return out


def extract_dem_features(villages: gpd.GeoDataFrame, data_dir: Path, village_zip: Path) -> pd.DataFrame:
    dem_path, dem_label = resolve_dem_raster(data_dir, villages)
    if dem_path is None:
        return pd.DataFrame(
            {
                "Village_ID": villages["Village_ID"],
                "Elevation": np.nan,
                "elevation_min": np.nan,
                "elevation_max": np.nan,
                "elevation_source": dem_label,
            }
        )

    if rasterio is None or raster_mask is None:
        warnings.warn(
            "rasterio unavailable; real DEM raster is present but raster-based zonal statistics cannot run yet.",
            RuntimeWarning,
        )
        return pd.DataFrame(
            {
                "Village_ID": villages["Village_ID"],
                "Elevation": np.nan,
                "elevation_min": np.nan,
                "elevation_max": np.nan,
                "elevation_source": "missing_rasterio",
            }
        )

    rows = []
    print(f"[DEM] Using rasterio zonal statistics from {dem_path.name}")
    with rasterio.open(dem_path) as src:
        villages_proj = villages[["Village_ID", "geometry"]].to_crs(src.crs or DEFAULT_CRS)
        for _, village in villages_proj.iterrows():
            row = {
                "Village_ID": int(village["Village_ID"]),
                "Elevation": np.nan,
                "elevation_min": np.nan,
                "elevation_max": np.nan,
                "elevation_source": dem_label,
            }
            try:
                clipped, _ = raster_mask(src, [village.geometry.__geo_interface__], crop=True, filled=False)
                band = np.asarray(clipped[0].filled(np.nan), dtype=float)
                valid = band[np.isfinite(band)]
                if valid.size:
                    row["Elevation"] = float(valid.mean())
                    row["elevation_min"] = float(valid.min())
                    row["elevation_max"] = float(valid.max())
            except Exception:
                pass
            rows.append(row)
    return pd.DataFrame(rows)


def extract_piezometer_features(villages: gpd.GeoDataFrame, pz_xlsx: Path) -> pd.DataFrame:
    pz = pd.read_excel(pz_xlsx)
    pz.columns = [str(c).strip() for c in pz.columns]

    lat_col = next((c for c in pz.columns if "latitude" in c.lower()), None)
    lon_col = next((c for c in pz.columns if "longitude" in c.lower()), None)
    district_col = next((c for c in pz.columns if c.lower() == "district"), None)
    mandal_col = next((c for c in pz.columns if "mandal" in c.lower()), None)
    village_col = next((c for c in pz.columns if "village" in c.lower()), None)
    elev_col = next((c for c in pz.columns if "msl" in c.lower()), None)
    depth_col = next((c for c in pz.columns if "total" in c.lower() and "depth" in c.lower()), None)
    aquifer_col = next((c for c in pz.columns if "principal aquifer" in c.lower()), None)

    if lat_col is None or lon_col is None:
        raise ValueError("Piezometer file is missing latitude/longitude columns")

    date_pairs: list[tuple[pd.Timestamp, object]] = []
    for c in pz.columns:
        parsed = parse_month_timestamp(c)
        if parsed is None:
            continue
        if parsed < GW_PUBLIC_START or parsed > GW_PUBLIC_END:
            continue
        date_pairs.append((parsed, c))
    if not date_pairs:
        raise ValueError("Piezometer file has no date-wise water level columns")

    date_pairs.sort(key=lambda item: item[0])
    date_cols = [col for _, col in date_pairs]
    full_dates = [ts.strftime("%Y-%m") for ts, _ in date_pairs]
    pz[date_cols] = pz[date_cols].apply(pd.to_numeric, errors="coerce")
    pz["GW_Level"] = pz[date_cols].mean(axis=1, skipna=True)
    pz["obs_elevation_msl"] = safe_numeric(pz[elev_col]) if elev_col else np.nan
    pz["obs_total_depth_m"] = safe_numeric(pz[depth_col]) if depth_col else np.nan
    pz["principal_aquifer_obs"] = pz[aquifer_col].astype(str).str.strip() if aquifer_col else "Unknown"
    pz["monthly_depths_full"] = pz[date_cols].apply(
        lambda row: json.dumps(serialize_monthly_values(row.tolist())),
        axis=1,
    )
    pz["monthly_depths_full_dates"] = json.dumps(full_dates)
    pz["monthly_depths_full_pairs"] = pz[date_cols].apply(
        lambda row: json.dumps(series_pairs(full_dates, serialize_monthly_values(row.tolist()))),
        axis=1,
    )
    pz["available_years"] = json.dumps(available_years_from_labels(full_dates))

    tail_cols = date_cols[-24:]
    tail_dates = full_dates[-24:]
    pz["monthly_depths"] = pz[tail_cols].apply(
        lambda row: json.dumps(serialize_monthly_values(row.tolist())),
        axis=1,
    )
    pz["monthly_depths_dates"] = json.dumps(tail_dates)

    pz[lat_col] = safe_numeric(pz[lat_col])
    pz[lon_col] = safe_numeric(pz[lon_col])
    pz = pz.dropna(subset=[lat_col, lon_col])

    pz_gdf = gpd.GeoDataFrame(
        pz,
        geometry=gpd.points_from_xy(pz[lon_col], pz[lat_col]),
        crs=DEFAULT_CRS,
    )

    joined = gpd.sjoin(
        pz_gdf,
        villages[["Village_ID", "Village_Name", "Village_Name_Norm", "District", "Mandal", "geometry"]],
        how="left",
        predicate="within",
    )

    unmatched = joined["Village_ID"].isna()
    if unmatched.any():
        village_lookup = villages.drop_duplicates("Village_Name_Norm").set_index("Village_Name_Norm")["Village_ID"].to_dict()
        trio_lookup = (
            villages.assign(
                district_norm=villages["District"].map(normalize_text),
                mandal_norm=villages["Mandal"].map(normalize_text),
                village_norm=villages["Village_Name"].map(normalize_text),
            )
            .drop_duplicates(["district_norm", "mandal_norm", "village_norm"])
            .set_index(["district_norm", "mandal_norm", "village_norm"])["Village_ID"]
            .to_dict()
        )

        def lookup_row(row: pd.Series) -> int | None:
            district_norm = normalize_text(row.get(district_col)) if district_col else ""
            mandal_norm = normalize_text(row.get(mandal_col)) if mandal_col else ""
            village_norm = normalize_text(row.get(village_col)) if village_col else ""
            if district_norm and mandal_norm and village_norm:
                match = trio_lookup.get((district_norm, mandal_norm, village_norm))
                if match is not None:
                    return int(match)
            if village_norm:
                match = village_lookup.get(village_norm)
                if match is not None:
                    return int(match)
            return None

        joined.loc[unmatched, "Village_ID"] = joined.loc[unmatched].apply(lookup_row, axis=1)

    joined["Village_ID"] = safe_numeric(joined["Village_ID"])
    joined = joined.dropna(subset=["Village_ID"]).copy()
    joined["Village_ID"] = joined["Village_ID"].astype(int)

    rows = []
    for village_id, group in joined.groupby("Village_ID", dropna=False):
        full_values = [
            None if pd.isna(group[col].mean(skipna=True)) else round(float(group[col].mean(skipna=True)), 4)
            for col in date_cols
        ]
        long_term_avg = compute_long_term_avg(full_values)
        trend_slope = compute_trend_slope(full_values)
        seasonal_variation = compute_seasonal_variation(full_values, full_dates)
        rows.append(
            {
                "Village_ID": int(village_id),
                "GW_Level": last_finite(full_values),
                "obs_station_count": int(len(group)),
                "obs_elevation_msl_mean": None if pd.isna(group["obs_elevation_msl"].mean(skipna=True)) else round(float(group["obs_elevation_msl"].mean(skipna=True)), 4),
                "obs_total_depth_m": None if pd.isna(group["obs_total_depth_m"].mean(skipna=True)) else round(float(group["obs_total_depth_m"].mean(skipna=True)), 4),
                "actual_last_month": last_finite(full_values),
                "target_last_month": last_finite(full_values),
                "long_term_avg": long_term_avg,
                "trend_slope": trend_slope,
                "seasonal_variation": seasonal_variation,
                "available_years": json.dumps(available_years_from_labels(full_dates)),
                "principal_aquifer_obs": mode_or_unknown(group["principal_aquifer_obs"]),
                "monthly_depths_full": full_values,
                "monthly_depths_full_dates": full_dates,
                "monthly_depths_full_pairs": series_pairs(full_dates, full_values),
                "monthly_depths": full_values[-24:],
                "monthly_depths_dates": tail_dates,
            }
        )
    return pd.DataFrame(rows)


def extract_pumping_by_village(villages: gpd.GeoDataFrame, pumping_xlsx: Path) -> pd.DataFrame:
    pump = pd.read_excel(pumping_xlsx)
    pump.columns = [str(c).strip() for c in pump.columns]

    village_col = next((c for c in pump.columns if c.lower() == "village"), None)
    wells_col = next((c for c in pump.columns if "functioning wells" in c.lower()), None)
    monsoon_col = next((c for c in pump.columns if "estimated draft per well" in c.lower()), None)
    non_monsoon_col = next((c for c in pump.columns if c.lower().startswith("unnamed")), None)
    structure_col = next((c for c in pump.columns if "structure type" in c.lower()), None)

    if village_col is None or wells_col is None or monsoon_col is None:
        raise ValueError("Pumping file missing required columns")

    pump[wells_col] = safe_numeric(pump[wells_col])
    pump[monsoon_col] = safe_numeric(pump[monsoon_col])
    if non_monsoon_col is not None:
        pump[non_monsoon_col] = safe_numeric(pump[non_monsoon_col])

    if non_monsoon_col is not None:
        avg_draft = pump[[monsoon_col, non_monsoon_col]].mean(axis=1, skipna=True)
    else:
        avg_draft = pump[monsoon_col]

    pump["Pumping"] = safe_numeric(pump[wells_col]) * safe_numeric(avg_draft)

    lookup = villages.drop_duplicates("Village_Name_Norm").set_index("Village_Name_Norm")["Village_ID"].to_dict()
    pump["Village_ID"] = pump[village_col].map(normalize_text).map(lookup)
    pump = pump.dropna(subset=["Village_ID", "Pumping"]).copy()
    pump["Village_ID"] = pump["Village_ID"].astype(int)

    agg = pump.groupby("Village_ID", as_index=False).agg(
        Pumping=("Pumping", "mean"),
        pumping_functioning_wells=(wells_col, "mean"),
        pumping_monsoon_draft_ha_m=(monsoon_col, "mean"),
        dominant_structure_type=(structure_col, lambda s: mode_or_unknown(s)) if structure_col else ("Village_ID", "size"),
    )
    if "dominant_structure_type" not in agg.columns:
        agg["dominant_structure_type"] = "Unknown"
    return agg


def build_dataset(data_dir: Path, output_csv: Path) -> pd.DataFrame:
    village_zip = data_dir / "Village_Mandal_DEM_Soils_MITanks_Krishna.zip"
    lulc_zip = data_dir / "KrishnaLULC.zip"
    pz_xlsx = data_dir / "PzWaterLevel_2024.xlsx"
    pumping_xlsx = data_dir / "Pumping Data.xlsx"
    aquifer_zip = data_dir / "Aquifers_Krishna.zip"
    gm_zip = data_dir / "GM_Krishna.zip"
    wells_zip = data_dir / "GTWells_Krishna.zip"

    villages = load_villages(village_zip)
    base = villages[["Village_ID", "Village_Name", "District", "Mandal", "State"]].copy()

    lulc_df = extract_lulc_percentages(villages, lulc_zip)
    soil_df = extract_soil_by_village(villages, village_zip)
    aquifer_df = extract_aquifer_by_village(villages, aquifer_zip)
    geom_df = extract_geomorphology_by_village(villages, gm_zip)
    wells_df = extract_gtwell_features(villages, wells_zip)
    tank_df = extract_tank_features(villages, village_zip)
    dem_df = extract_dem_features(villages, data_dir, village_zip)
    pz_df = extract_piezometer_features(villages, pz_xlsx)
    pumping_df = extract_pumping_by_village(villages, pumping_xlsx)

    final = base.copy()
    for frame in [lulc_df, pumping_df, pz_df, dem_df, soil_df, aquifer_df, geom_df, wells_df, tank_df]:
        final = final.merge(frame, on="Village_ID", how="left")

    # Preserve the legacy training columns expected by train_from_csv.
    numeric_fill_zero = [
        "Water%",
        "Trees%",
        "Crops%",
        "Built%",
        "Bare%",
        "Rangeland%",
        "Pumping",
        "GW_Level",
        "Elevation",
        "pumping_functioning_wells",
        "pumping_monsoon_draft_ha_m",
        "obs_station_count",
        "obs_elevation_msl_mean",
        "obs_total_depth_m",
        "actual_last_month",
        "target_last_month",
        "wells_total",
        "wells_working_pct",
        "avg_bore_depth_m",
        "avg_pump_capacity_hp",
        "avg_extant_land_hac",
        "tank_count",
        "distance_to_nearest_tank_km",
        "built_area_change_pct",
        "elevation_min",
        "elevation_max",
    ]
    for col in numeric_fill_zero:
        if col in final.columns:
            final[col] = safe_numeric(final[col]).fillna(0.0)
    for col in ["long_term_avg", "trend_slope", "seasonal_variation"]:
        if col in final.columns:
            final[col] = pd.to_numeric(final[col], errors="coerce")

    text_fill_unknown = [
        "Soil",
        "Soil_Taxonomy",
        "Soil_Map_Unit",
        "aquifer_code",
        "aquifer_type",
        "geomorphology",
        "dominant_irrigation",
        "dominant_crop_type",
        "dominant_well_type",
        "principal_aquifer_obs",
        "dominant_structure_type",
        "elevation_source",
        "lulc_start_dominant",
        "lulc_end_dominant",
    ]
    for col in text_fill_unknown:
        if col in final.columns:
            final[col] = final[col].fillna("Unknown").astype(str)

    if "monthly_depths" in final.columns:
        final["monthly_depths"] = final["monthly_depths"].fillna("[]")
    if "monthly_depths_full_pairs" in final.columns:
        final["monthly_depths_full_pairs"] = final["monthly_depths_full_pairs"].fillna("[]")
    if "available_years" in final.columns:
        final["available_years"] = final["available_years"].fillna("[]")

    # Backward-compatible Elevation field: prefer DEM, otherwise piezometer MSL.
    if "Elevation" in final.columns and "obs_elevation_msl_mean" in final.columns:
        missing_dem = safe_numeric(final["Elevation"]).fillna(0.0) == 0.0
        fallback_obs = safe_numeric(final["obs_elevation_msl_mean"]).fillna(0.0)
        final.loc[missing_dem, "Elevation"] = fallback_obs[missing_dem]
        if "elevation_source" in final.columns:
            final.loc[missing_dem, "elevation_source"] = np.where(
                fallback_obs[missing_dem] > 0,
                "piezometer_msl_fallback",
                final.loc[missing_dem, "elevation_source"],
            )

    flooded_proxy = series_or_default(final, "flooded_vegetation_pct")
    final["rainfall_proxy"] = flooded_proxy
    final["recharge_index"] = (
        series_or_default(final, "Water%")
        + series_or_default(final, "tank_count")
        + final["rainfall_proxy"]
    )
    final["extraction_stress"] = (
        series_or_default(final, "Pumping")
        / (series_or_default(final, "wells_total") + 1.0)
    )
    final["terrain_gradient"] = (
        series_or_default(final, "elevation_max")
        - series_or_default(final, "elevation_min")
    )
    aquifer_types = final["aquifer_type"] if "aquifer_type" in final.columns else pd.Series("Unknown", index=final.index)
    final["aquifer_storage_factor"] = aquifer_types.map(aquifer_storage_factor_from_type)

    ordered_columns = [
            "Village_ID",
            "Village_Name",
            "District",
            "Mandal",
            "State",
            "Water%",
            "Trees%",
            "Crops%",
            "Built%",
            "Bare%",
            "Rangeland%",
            "Pumping",
            "GW_Level",
            "Soil",
            "Elevation",
            "aquifer_code",
            "aquifer_type",
            "geomorphology",
            "wells_total",
            "wells_working_pct",
            "avg_bore_depth_m",
            "avg_pump_capacity_hp",
            "avg_extant_land_hac",
            "dominant_irrigation",
            "dominant_crop_type",
            "dominant_well_type",
            "tank_count",
            "distance_to_nearest_tank_km",
            "obs_station_count",
            "monthly_depths",
            "monthly_depths_full",
            "monthly_depths_full_pairs",
            "monthly_depths_dates",
            "monthly_depths_full_dates",
            "available_years",
            "obs_elevation_msl_mean",
            "obs_total_depth_m",
            "actual_last_month",
            "target_last_month",
            "long_term_avg",
            "trend_slope",
            "seasonal_variation",
            "principal_aquifer_obs",
            "pumping_functioning_wells",
            "pumping_monsoon_draft_ha_m",
            "dominant_structure_type",
            "Soil_Taxonomy",
            "Soil_Map_Unit",
            "elevation_min",
            "elevation_max",
            "terrain_gradient",
            "elevation_source",
            "rainfall_proxy",
            "recharge_index",
            "extraction_stress",
            "aquifer_storage_factor",
            "lulc_latest_year",
            "lulc_start_year",
            "lulc_end_year",
            "lulc_start_dominant",
            "lulc_end_dominant",
            "built_area_change_pct",
            "flooded_vegetation_pct",
            "snow_ice_pct",
            "clouds_pct",
    ]
    ordered_columns += [col for col in final.columns if re.match(r".+_\d{4}%$", col)]
    final = final[[col for col in ordered_columns if col in final.columns]]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(output_csv, index=False)

    frontend_dataset_path = Path("frontend/public/data/final_dataset.json")
    frontend_dataset_path.parent.mkdir(parents=True, exist_ok=True)
    export = final.copy()
    missing_dem = export.get("elevation_source", pd.Series(index=export.index, dtype=object)).astype(str) == "missing_dem_raster"
    for col in ["Elevation", "elevation_min", "elevation_max", "terrain_gradient"]:
      if col in export.columns:
        export.loc[missing_dem, col] = np.nan

    missing_piezometer = safe_numeric(export.get("obs_station_count", pd.Series(index=export.index))).fillna(0) <= 0
    for col in ["GW_Level", "obs_elevation_msl_mean", "obs_total_depth_m", "actual_last_month", "target_last_month"]:
        if col in export.columns:
            export.loc[missing_piezometer, col] = np.nan

    lulc_current_cols = ["Water%", "Trees%", "Crops%", "Built%", "Bare%", "Rangeland%"]
    if all(col in export.columns for col in lulc_current_cols):
        lulc_zero = export[lulc_current_cols].apply(lambda row: float(pd.to_numeric(row, errors="coerce").fillna(0).sum()), axis=1) == 0
        export.loc[lulc_zero, lulc_current_cols] = np.nan

    frontend_dataset_path.write_text(
        export.where(pd.notna(export), None).to_json(orient="records", indent=2),
        encoding="utf-8",
    )
    return final


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate village-level groundwater ML dataset from Krishna source files")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"), help="Directory containing source ZIP/XLSX files")
    parser.add_argument("--out", type=Path, default=Path("output/final_dataset.csv"), help="Output CSV path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    final = build_dataset(args.data_dir, args.out)
    print(f"ML dataset ready: {args.out} ({len(final)} rows)")
    print("Columns:", ", ".join(final.columns))


if __name__ == "__main__":
    main()
