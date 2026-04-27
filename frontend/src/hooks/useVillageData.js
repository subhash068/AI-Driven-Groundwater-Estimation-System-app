import { useState, useEffect, useMemo } from 'react';
import { buildLocationKey, normalizeLocationName } from '../utils/mapUtils';
import { INDIAN_STATES } from '../constants/data';

const DEFAULT_STATE = "Andhra Pradesh";
const EXCLUDED_DISTRICTS = new Set([
  "guntur",
  "west godavari"
]);

const DISTRICT_VILLAGE_DATASET_CANDIDATES = [
  "/data/village_boundaries_imputed.geojson",
  "/data/village_boundaries.geojson",
  "/data/villages.geojson",
  "/data/village_boundaries_ntr.geojson",
  "/data/villages_ntr.geojson"
];

function featureLocationKey(feature) {
  const props = feature?.properties || {};
  return buildLocationKey(props.district, props.mandal, props.village_name);
}

function featureCompletenessScore(feature) {
  const props = feature?.properties || {};
  let score = feature?.geometry ? 1 : 0;
  for (const value of Object.values(props)) {
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

function normalizeFeatureProperties(feature, index) {
  const p = feature?.properties || {};
  const lc = Object.fromEntries(
    Object.entries(p).map(([k, v]) => [String(k).toLowerCase().trim(), v])
  );
  const villageName =
    lc.village_name ??
    lc.village ??
    lc.dvname ??
    lc.name ??
    `Village ${index + 1}`;
  const district = lc.district ?? lc.dname ?? "Unknown";
  const mandal = lc.mandal ?? lc.mname ?? lc.taluk ?? "Unknown";
  const state = lc.state ?? "Andhra Pradesh";
  const villageId = lc.village_id ?? lc.villageid ?? lc.id ?? index + 1;

  return {
    ...feature,
    properties: {
      ...p,
      village_id: villageId,
      village_name: String(villageName).trim(),
      district: String(district).trim(),
      mandal: String(mandal).trim(),
      state: String(state).trim(),
      location_key: buildLocationKey(district, mandal, villageName)
    }
  };
}

function normalizeVillageGeojson(geojson) {
  const features = Array.isArray(geojson?.features) ? geojson.features : [];
  return {
    ...geojson,
    type: "FeatureCollection",
    features: features
      .filter((f) => f && f.geometry)
      .filter((f) => {
        const districtName = String(f?.properties?.district || "").trim();
        return !EXCLUDED_DISTRICTS.has(normalizeLocationName(districtName));
      })
      .map((f, i) => normalizeFeatureProperties(f, i))
  };
}

function optionLabel(district, mandal, villageName = null) {
  const parts = [String(district || "").trim(), String(mandal || "").trim()];
  if (villageName) {
    parts.push(String(villageName || "").trim());
  }
  return parts.filter(Boolean).join(" / ");
}

async function fetchJsonIfValid(path) {
  try {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const text = (await response.text()).trim();
    if (!text) return null;
    const contentType = String(response.headers.get("content-type") || "").toLowerCase();
    const looksJson = text.startsWith("{") || text.startsWith("[");
    const jsonLikeType =
      contentType.includes("application/json") ||
      contentType.includes("application/geo+json") ||
      contentType.includes("text/plain");
    if (!looksJson && !jsonLikeType) return null;
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isLikelyPlaceholderDataset(geojson) {
  const features = Array.isArray(geojson?.features) ? geojson.features : [];
  if (features.length !== 1) return false;
  const feature = features[0];
  const villageName = String(feature?.properties?.village_name || "").trim().toLowerCase();
  return villageName === "sample village";
}

async function loadVillageGeojson() {
  const mergedByKey = new Map();
  const mergedSources = [];

  for (const path of DISTRICT_VILLAGE_DATASET_CANDIDATES) {
    const geojson = await fetchJsonIfValid(path);
    if (!geojson || !Array.isArray(geojson.features)) continue;
    if (isLikelyPlaceholderDataset(geojson)) continue;
    const normalized = normalizeVillageGeojson(geojson);
    if (!Array.isArray(normalized.features) || !normalized.features.length) continue;
    mergedSources.push(path);
    normalized.features.forEach((feature) => {
      const key = featureLocationKey(feature);
      if (!key) return;
      const existing = mergedByKey.get(key);
      if (!existing || featureCompletenessScore(feature) > featureCompletenessScore(existing)) {
        mergedByKey.set(key, feature);
      }
    });
  }
  if (mergedByKey.size) {
    return {
      geojson: normalizeVillageGeojson({
        type: "FeatureCollection",
        features: Array.from(mergedByKey.values())
      }),
      sourcePath: mergedSources.join(", ")
    };
  }

  return null;
}

export function useVillageData(filters) {
  const [villages, setVillages] = useState(null);
  const [sidebarLocations, setSidebarLocations] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dataSource, setDataSource] = useState(null);

  const { state, district, mandal, villageName } = filters;

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const [villageGeojsonResult, sidebarJson] = await Promise.all([
          loadVillageGeojson(),
          fetchJsonIfValid("/data/excel_locations.json")
        ]);

        if (!villageGeojsonResult) {
          setVillages({ type: "FeatureCollection", features: [] });
          setDataSource(null);
          setError("No real village boundary dataset found. Add /public/data/village_boundaries.geojson.");
        } else {
          setVillages(villageGeojsonResult.geojson);
          setDataSource(villageGeojsonResult.sourcePath);
          setError(null);
        }

        setSidebarLocations(sidebarJson);
      } catch (err) {
        setError(err?.message || "Failed to load village boundaries.");
        setVillages({ type: "FeatureCollection", features: [] });
        setDataSource(null);
        setSidebarLocations(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filteredGeojson = useMemo(() => {
    if (!villages) return null;
    const features = villages.features.filter((f) => {
      const p = f.properties || {};
      const featureState = String(p.state || DEFAULT_STATE).trim();
      const stateMatch = state
        ? normalizeLocationName(featureState) === normalizeLocationName(state)
        : true;
      const districtMatch = district
        ? normalizeLocationName(p.district) === normalizeLocationName(district)
        : true;
      const mandalMatch = mandal
        ? normalizeLocationName(p.mandal) === normalizeLocationName(mandal)
        : true;
      const villageMatch = villageName
        ? normalizeLocationName(p.village_name) === normalizeLocationName(villageName)
        : true;
      return stateMatch && districtMatch && mandalMatch && villageMatch;
    });

    const hasActiveFilters = Boolean(state || district || mandal || villageName);
    if (!hasActiveFilters && features.length === 0 && (villages.features?.length || 0) > 0) {
      return villages;
    }
    return { ...villages, features };
  }, [villages, state, district, mandal, villageName]);

  const stateOptions = useMemo(() => {
    return INDIAN_STATES;
  }, [district]);

  const districtOptions = useMemo(() => {
    if (!villages) return [];
    const stateScopedFeatures = villages.features.filter((f) => {
      const featureState = String(f.properties?.state || DEFAULT_STATE).trim();
      return state
        ? normalizeLocationName(featureState) === normalizeLocationName(state)
        : true;
    });
    return Array.from(
      new Set(
        stateScopedFeatures
          .map((f) => String(f.properties?.district || "").trim())
          .filter((districtName) => {
            if (!districtName) return false;
            return !EXCLUDED_DISTRICTS.has(normalizeLocationName(districtName));
          })
      )
    ).sort((a, b) => a.localeCompare(b));
  }, [villages, state]);

  const districtCount = useMemo(() => {
    if (!villages) return 0;
    return new Set(
      villages.features
        .map((f) => String(f.properties?.district || "").trim())
        .filter((districtName) => districtName && !EXCLUDED_DISTRICTS.has(normalizeLocationName(districtName)))
    ).size;
  }, [villages]);

  const stateScopedFeatures = useMemo(() => {
    if (!villages?.features?.length) return [];
    return villages.features.filter((f) => {
      const featureState = String(f.properties?.state || DEFAULT_STATE).trim();
      return state
        ? normalizeLocationName(featureState) === normalizeLocationName(state)
        : true;
    });
  }, [villages, state]);

  const districtScopedFeatures = useMemo(() => {
    if (!stateScopedFeatures.length) return [];
    return stateScopedFeatures.filter((f) => {
      const districtName = String(f.properties?.district || "").trim();
      return district
        ? normalizeLocationName(districtName) === normalizeLocationName(district)
        : true;
    });
  }, [stateScopedFeatures, district]);

  const mandalOptions = useMemo(() => {
    if (!villages) return [];
    const sourceFeatures = district ? districtScopedFeatures : stateScopedFeatures;
    const map = new Map();
    sourceFeatures.forEach((feature) => {
      const props = feature.properties || {};
      const districtName = String(props.district || "").trim();
      const mandalName = String(props.mandal || "").trim();
      if (!mandalName) return;
      const key = `${normalizeLocationName(districtName)}|${normalizeLocationName(mandalName)}`;
      if (!map.has(key)) {
        map.set(key, {
          value: mandalName,
          label: optionLabel(districtName, mandalName),
          district: districtName
        });
      }
    });
    return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [villages, stateScopedFeatures, districtScopedFeatures, district]);

  const villageOptions = useMemo(() => {
    if (!villages) return [];
    const sourceFeatures = district ? districtScopedFeatures : stateScopedFeatures;
    const map = new Map();
    sourceFeatures.forEach((feature) => {
      const props = feature.properties || {};
      const districtName = String(props.district || "").trim();
      const mandalName = String(props.mandal || "").trim();
      const village = String(props.village_name || "").trim();
      if (!village) return;
      if (mandal && normalizeLocationName(mandalName) !== normalizeLocationName(mandal)) return;
      const key = [
        normalizeLocationName(districtName),
        normalizeLocationName(mandalName),
        normalizeLocationName(village)
      ].join("|");
      if (!map.has(key)) {
        map.set(key, {
          value: village,
          label: optionLabel(districtName, mandalName, village),
          district: districtName,
          mandal: mandalName
        });
      }
    });
    return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [villages, stateScopedFeatures, districtScopedFeatures, district, mandal]);

  return {
    villages,
    filteredGeojson,
    stateOptions,
    districtOptions,
    mandalOptions,
    villageOptions,
    loading,
    error,
    dataSource,
    totalCount: villages?.features?.length || 0,
    districtCount
  };
}
