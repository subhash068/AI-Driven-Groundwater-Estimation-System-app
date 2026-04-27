import { useEffect, useMemo, useState } from "react";
import { buildLocationKey, normalizeLocationName } from "../utils/mapUtils";
import pumpingWorkbook from "../constants/pumping_data.json";

const UNIFIED_DATASET_CANDIDATES = [
  "/data/final_dataset.json",
  "/data/map_data_predictions.geojson",
  "/data/map_data_predictions_ntr.geojson"
];

const DISTRICT_DATASET_CANDIDATES = [
  "/data/final_dataset.json",
  "/data/map_data_predictions.geojson",
  "/data/map_data_predictions_ntr.geojson",
  "/data/final_dataset_ntr.json"
];

const FALLBACK_DATASET_CANDIDATES = [
  "/data/village_boundaries_imputed.geojson",
  "/data/village_boundaries.geojson",
  "/data/villages.geojson",
  "/data/village_boundaries_ntr.geojson",
  "/data/villages_ntr.geojson"
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

function buildPumpingWellsIndex() {
  const rows = Array.isArray(pumpingWorkbook?.rows) ? pumpingWorkbook.rows : [];
  const index = new Map();

  for (const row of rows) {
    const district = normalizeText(row?.district, "");
    const mandal = normalizeText(row?.mandal, "");
    const village = normalizeText(row?.village, "");
    if (!district || !mandal || !village) continue;

    const key = buildLocationKey(district, mandal, village);
    if (!key) continue;

    const wells = Number(row?.functioning_wells);
    if (!Number.isFinite(wells)) continue;

    const current = index.get(key) || { functioning_wells: 0, row_count: 0 };
    index.set(key, {
      functioning_wells: current.functioning_wells + wells,
      row_count: current.row_count + 1
    });
  }

  return index;
}

const PUMPING_WELLS_BY_LOCATION = buildPumpingWellsIndex();

function recordCompletenessScore(record) {
  let score = 0;
  for (const value of Object.values(record || {})) {
    if (Array.isArray(value)) {
      if (value.length > 0) score += 1;
      continue;
    }
    if (value === null || value === undefined) continue;
    if (typeof value === "string") {
      if (value.trim()) score += 1;
      continue;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      score += 1;
      continue;
    }
    if (typeof value === "boolean") score += 1;
  }
  return score;
}

function isSyntheticVillageName(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  return !normalized || normalized === "forest";
}

function getRecordLocationKey(row) {
  if (!row || typeof row !== "object") return "";
  return row.location_key || buildLocationKey(row?.district || "", row?.mandal || "", row?.village_name || "");
}

function setRicherRecord(map, key, row) {
  if (!map.has(key)) {
    map.set(key, row);
    return;
  }
  const current = map.get(key);
  if (recordCompletenessScore(row) > recordCompletenessScore(current)) {
    map.set(key, row);
  }
}

function mergeRecordsByLocationKey(records) {
  const merged = new Map();
  records.forEach((row) => {
    if (isSyntheticVillageName(row?.village_name ?? row?.Village_Name ?? row?.village ?? row?.name)) return;
    const key = getRecordLocationKey(row);
    if (!key) return;
    setRicherRecord(merged, key, row);
  });
  return Array.from(merged.values());
}

function logDuplicateCompositeKeys(records) {
  const seen = new Set();
  const duplicates = [];

  records.forEach((row) => {
    if (isSyntheticVillageName(row?.village_name ?? row?.Village_Name ?? row?.village ?? row?.name)) return;
    const key = getRecordLocationKey(row);
    if (!key) return;
    if (seen.has(key)) {
      duplicates.push(key);
      return;
    }
    seen.add(key);
  });

  // Removed console logging to prevent console spam

  return {
    duplicateCount: duplicates.length,
    duplicates
  };
}

function logCrossDistrictCollisions(records) {
  const byVillageName = new Map();
  const collisions = [];

  records.forEach((row) => {
    const villageName = normalizeText(row?.village_name, "");
    const district = normalizeText(row?.district, "");
    if (!villageName || !district || isSyntheticVillageName(villageName)) return;
    const bucket = byVillageName.get(villageName) || new Map();
    if (!bucket.has(district)) {
      bucket.set(district, getRecordLocationKey(row));
    }
    byVillageName.set(villageName, bucket);
  });

  byVillageName.forEach((districts, villageName) => {
    if (districts.size > 1) {
      collisions.push({
        village_name: villageName,
        districts: Array.from(districts.keys())
      });
    }
  });

  // Removed console logging to prevent console spam

  return {
    collisionCount: collisions.length,
    collisions
  };
}

function normalizeRecord(input, index) {
  const props = input?.properties || input || {};
  const rawVillageName = String(props.village_name ?? props.Village_Name ?? props.name ?? props.village ?? "").trim();
  if (!rawVillageName || rawVillageName.toLowerCase() === "forest") return null;
  const district = normalizeText(props.district ?? props.District);
  const mandal = normalizeText(props.mandal ?? props.Mandal);
  const village_name = normalizeText(rawVillageName, `Village ${index + 1}`);
  const locationKey = buildLocationKey(district, mandal, village_name);
  const pumpingWells = Number(
    PUMPING_WELLS_BY_LOCATION.get(locationKey)?.functioning_wells ??
    props.pumping_functioning_wells ??
    props.functioning_wells ??
    0
  );
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
    functioning_wells: pumpingWells,
    pumping_functioning_wells: pumpingWells,
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
      records: payload.map((row, index) => normalizeRecord(row, index)).filter(Boolean),
      sourcePath
    };
  }

  if (payload?.type === "FeatureCollection" && Array.isArray(payload.features)) {
    return {
      records: payload.features.map((feature, index) => normalizeRecord(feature, index)).filter(Boolean),
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
  const [integritySummary, setIntegritySummary] = useState({
    duplicateCount: 0,
    duplicates: [],
    collisionCount: 0,
    collisions: []
  });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        const loadedRecords = [];
        const districtSources = [];
        const candidatePaths = Array.from(new Set([
          ...UNIFIED_DATASET_CANDIDATES,
          ...DISTRICT_DATASET_CANDIDATES
        ]));
        for (const path of candidatePaths) {
          const payload = await fetchJsonIfValid(path);
          const normalized = normalizeDataset(payload, path);
          if (!normalized) continue;
          loadedRecords.push(...normalized.records);
          districtSources.push(path);
        }

        if (loadedRecords.length > 0) {
          const merged = mergeRecordsByLocationKey(loadedRecords);
          const duplicateSummary = logDuplicateCompositeKeys(merged);
          const collisionSummary = logCrossDistrictCollisions(merged);
          if (!active) return;
          setRecords(merged);
          setIntegritySummary({
            ...duplicateSummary,
            ...collisionSummary
          });
          setSourcePath(districtSources.join(", "));
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
        setIntegritySummary({
          duplicateCount: 0,
          duplicates: [],
          collisionCount: 0,
          collisions: []
        });
        setSourcePath(null);
        setError("No dashboard dataset found under /public/data.");
      } catch (err) {
        if (!active) return;
        setRecords([]);
        setIntegritySummary({
          duplicateCount: 0,
          duplicates: [],
          collisionCount: 0,
          collisions: []
        });
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
      const villageId = Number(row.village_id);
      if (!Number.isFinite(villageId)) return;
      setRicherRecord(map, villageId, row);
    });
    return map;
  }, [records]);

  const recordsByLocation = useMemo(() => {
    const map = new Map();
    records.forEach((row) => {
      const key = getRecordLocationKey(row);
      if (!key) return;
      setRicherRecord(map, key, row);
    });
    return map;
  }, [records]);

  return {
    records,
    recordsById,
    recordsByLocation,
    sourcePath,
    loading,
    error,
    integritySummary
  };
}
