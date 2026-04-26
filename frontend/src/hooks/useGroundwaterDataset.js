import { useEffect, useMemo, useState } from "react";
import { buildLocationKey, normalizeLocationName } from "../utils/mapUtils";

const UNIFIED_DATASET_CANDIDATES = [
  "/data/final_dataset.json",
  "/data/map_data_predictions.geojson"
];

const DISTRICT_DATASET_CANDIDATES = [
  "/data/final_dataset.json",
  "/data/map_data_predictions.geojson",
  "/data/final_dataset_ntr.json"
];

const FALLBACK_DATASET_CANDIDATES = [
  "/data/village_boundaries.geojson",
  "/data/villages.geojson"
];

function toNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeText(value, fallback = "Unknown") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function normalizeSeriesEntry(entry) {
  if (entry === null || entry === undefined || entry === "") return null;
  const numeric = Number(entry);
  return Number.isFinite(numeric) ? numeric : null;
}

function parseMonthlyDepths(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => normalizeSeriesEntry(entry));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((entry) => normalizeSeriesEntry(entry));
      }
    } catch {
      return [];
    }
  }
  return [];
}

function parseStringArray(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => (entry === null || entry === undefined ? "" : String(entry)));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((entry) => (entry === null || entry === undefined ? "" : String(entry)));
      }
    } catch {
      return [];
    }
  }
  return [];
}

function parseNumberArray(value) {
  if (Array.isArray(value)) {
    return value
      .map((entry) => Number(entry))
      .filter((entry) => Number.isFinite(entry));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed
          .map((entry) => Number(entry))
          .filter((entry) => Number.isFinite(entry));
      }
    } catch {
      return [];
    }
  }
  return [];
}

function parseObjectArray(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

function normalizeRecord(input, index) {
  const props = input?.properties || input || {};
  const district = normalizeText(props.district ?? props.District);
  const mandal = normalizeText(props.mandal ?? props.Mandal);
  const village_name = normalizeText(props.village_name ?? props.Village_Name ?? props.name ?? props.village, `Village ${index + 1}`);
  const locationKey = buildLocationKey(district, mandal, village_name);
  return {
    ...props,
    village_id: toNumber(props.village_id ?? props.Village_ID ?? props.villageId ?? index + 1, index + 1),
    village_name,
    district,
    mandal,
    state: normalizeText(props.state ?? props.State, "Andhra Pradesh"),
    location_key: locationKey,
    district_key: normalizeLocationName(district),
    mandal_key: normalizeLocationName(mandal),
    village_key: normalizeLocationName(village_name),
    water_pct: toNumber(props.water_pct ?? props["Water%"] ?? props.water, null),
    trees_pct: toNumber(props.trees_pct ?? props["Trees%"] ?? props.trees, null),
    flooded_vegetation_pct: toNumber(props.flooded_vegetation_pct ?? props["flooded_vegetation_pct"] ?? props.flooded_vegetation, null),
    crops_pct: toNumber(props.crops_pct ?? props["Crops%"] ?? props.crops, null),
    built_area_pct: toNumber(props.built_area_pct ?? props["Built%"] ?? props.built_area, null),
    bare_ground_pct: toNumber(props.bare_ground_pct ?? props["Bare%"] ?? props.bare_ground, null),
    snow_ice_pct: toNumber(props.snow_ice_pct ?? props["snow_ice_pct"] ?? props.snow_ice, null),
    clouds_pct: toNumber(props.clouds_pct ?? props["clouds_pct"] ?? props.clouds, null),
    rangeland_pct: toNumber(props.rangeland_pct ?? props["Rangeland%"] ?? props.rangeland, null),
    water_2011_pct: toNumber(props["water_2011%"] ?? props.water_2011_pct, null),
    trees_2011_pct: toNumber(props["trees_2011%"] ?? props.trees_2011_pct, null),
    flooded_vegetation_2011_pct: toNumber(props["flooded_vegetation_2011%"] ?? props.flooded_vegetation_2011_pct, null),
    crops_2011_pct: toNumber(props["crops_2011%"] ?? props.crops_2011_pct, null),
    built_2011_pct: toNumber(props["built_2011%"] ?? props.built_2011_pct, null),
    bare_2011_pct: toNumber(props["bare_2011%"] ?? props.bare_2011_pct, null),
    snow_ice_2011_pct: toNumber(props["snow_ice_2011%"] ?? props.snow_ice_2011_pct, null),
    clouds_2011_pct: toNumber(props["clouds_2011%"] ?? props.clouds_2011_pct, null),
    rangeland_2011_pct: toNumber(props["rangeland_2011%"] ?? props.rangeland_2011_pct, null),
    water_2021_pct: toNumber(props["water_2021%"] ?? props.water_2021_pct, null),
    trees_2021_pct: toNumber(props["trees_2021%"] ?? props.trees_2021_pct, null),
    flooded_vegetation_2021_pct: toNumber(props["flooded_vegetation_2021%"] ?? props.flooded_vegetation_2021_pct, null),
    crops_2021_pct: toNumber(props["crops_2021%"] ?? props.crops_2021_pct, null),
    built_2021_pct: toNumber(props["built_2021%"] ?? props.built_2021_pct, null),
    bare_2021_pct: toNumber(props["bare_2021%"] ?? props.bare_2021_pct, null),
    snow_ice_2021_pct: toNumber(props["snow_ice_2021%"] ?? props.snow_ice_2021_pct, null),
    clouds_2021_pct: toNumber(props["clouds_2021%"] ?? props.clouds_2021_pct, null),
    rangeland_2021_pct: toNumber(props["rangeland_2021%"] ?? props.rangeland_2021_pct, null),
    pumping_rate: toNumber(props.pumping_rate ?? props.Pumping, null),
    gw_level: toNumber(props.gw_level ?? props.GW_Level ?? props.predicted_groundwater_level, null),
    actual_last_month: toNumber(props.actual_last_month ?? props.target_last_month ?? props.GW_Level, null),
    obs_station_count: toNumber(props.obs_station_count, 0),
    obs_elevation_msl: toNumber(props.obs_elevation_msl ?? props.obs_elevation_msl_mean, null),
    obs_elevation_msl_mean: toNumber(props.obs_elevation_msl_mean, null),
    obs_total_depth_m: toNumber(props.obs_total_depth_m, null),
    long_term_avg: toNumber(props.long_term_avg, null),
    trend_slope: toNumber(props.trend_slope, null),
    seasonal_variation: toNumber(props.seasonal_variation, null),
    elevation: toNumber(props.elevation ?? props.Elevation, null),
    elevation_min: toNumber(props.elevation_min, null),
    elevation_max: toNumber(props.elevation_max, null),
    terrain_gradient: toNumber(props.terrain_gradient, null),
    recharge_index: toNumber(props.recharge_index, null),
    extraction_stress: toNumber(props.extraction_stress, null),
    aquifer_storage_factor: toNumber(props.aquifer_storage_factor, 1),
    rainfall_proxy: toNumber(props.rainfall_proxy, null),
    built_area_change_pct: toNumber(props.built_area_change_pct, null),
    soil: normalizeText(props.soil ?? props.Soil),
    soil_taxonomy: normalizeText(props.soil_taxonomy ?? props.Soil_Taxonomy),
    soil_map_unit: normalizeText(props.soil_map_unit ?? props.Soil_Map_Unit),
    aquifer_type: normalizeText(props.aquifer_type ?? props.Aquifer_Type),
    geomorphology: normalizeText(props.geomorphology),
    lulc_latest_year: toNumber(props.lulc_latest_year, 0),
    lulc_start_year: toNumber(props.lulc_start_year, 0),
    lulc_end_year: toNumber(props.lulc_end_year, 0),
    lulc_start_dominant: normalizeText(props.lulc_start_dominant),
    lulc_end_dominant: normalizeText(props.lulc_end_dominant),
    monthly_depths: parseMonthlyDepths(props.monthly_depths),
    monthly_depths_dates: parseStringArray(props.monthly_depths_dates),
    monthly_depths_full: parseMonthlyDepths(props.monthly_depths_full ?? props.monthly_depths_history),
    monthly_depths_full_dates: parseStringArray(props.monthly_depths_full_dates ?? props.monthly_depths_history_dates),
    monthly_depths_full_pairs: parseObjectArray(props.monthly_depths_full_pairs),
    available_years: parseNumberArray(props.available_years)
  };
}

async function fetchJsonIfValid(path) {
  try {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const text = (await response.text()).trim();
    if (!text) return null;
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function normalizeDataset(payload, sourcePath) {
  if (Array.isArray(payload)) {
    return {
      records: payload.map((row, index) => normalizeRecord(row, index)),
      sourcePath
    };
  }

  if (payload?.type === "FeatureCollection" && Array.isArray(payload.features)) {
    return {
      records: payload.features.map((feature, index) => normalizeRecord(feature, index)),
      sourcePath
    };
  }

  return null;
}

export function useGroundwaterDataset() {
  const [records, setRecords] = useState([]);
  const [sourcePath, setSourcePath] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        let unifiedRecords = [];
        let unifiedSource = null;
        for (const path of UNIFIED_DATASET_CANDIDATES) {
          const payload = await fetchJsonIfValid(path);
          const normalized = normalizeDataset(payload, path);
          if (!normalized) continue;
          unifiedRecords = normalized.records;
          unifiedSource = normalized.sourcePath;
          break;
        }

        const districtScoped = [];
        const districtSources = [];
        for (const path of DISTRICT_DATASET_CANDIDATES) {
          const payload = await fetchJsonIfValid(path);
          const normalized = normalizeDataset(payload, path);
          if (!normalized) continue;
          districtScoped.push(...normalized.records);
          districtSources.push(path);
        }

        if (districtScoped.length > 0 || unifiedRecords.length > 0) {
          const seen = new Set();
          const merged = [];
          for (const row of [...unifiedRecords, ...districtScoped]) {
            const key = row.location_key || buildLocationKey(row?.district || "", row?.mandal || "", row?.village_name || "");
            if (seen.has(key)) continue;
            seen.add(key);
            merged.push(row);
          }
          if (!active) return;
          setRecords(merged);
          setSourcePath([unifiedSource, districtSources.join(", ")].filter(Boolean).join(", "));
          setError(null);
          return;
        }

        for (const path of FALLBACK_DATASET_CANDIDATES) {
          const payload = await fetchJsonIfValid(path);
          const normalized = normalizeDataset(payload, path);
          if (!normalized) continue;
          if (!active) return;
          setRecords(normalized.records);
          setSourcePath(normalized.sourcePath);
          setError(null);
          return;
        }

        if (!active) return;
        setRecords([]);
        setSourcePath(null);
        setError("No dashboard dataset found under /public/data.");
      } catch (err) {
        if (!active) return;
        setRecords([]);
        setSourcePath(null);
        setError(err?.message || "Failed to load dashboard dataset.");
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  const recordsById = useMemo(() => {
    const map = new Map();
    records.forEach((row) => {
      map.set(Number(row.village_id), row);
    });
    return map;
  }, [records]);

  const recordsByLocation = useMemo(() => {
    const map = new Map();
    records.forEach((row) => {
      map.set(row.location_key || buildLocationKey(row.district, row.mandal, row.village_name), row);
    });
    return map;
  }, [records]);

  return {
    records,
    recordsById,
    recordsByLocation,
    sourcePath,
    loading,
    error
  };
}
