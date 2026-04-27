import { makeKey as buildLocationKey } from "../utils/key";

const API_BASE = String(
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE ||
  "/api"
).replace(/\/$/, "");
const endpointCircuitOpen = new Set();
const endpointCircuitReasons = new Map();
const apiStatusSubscribers = new Set();
const LIVE_API_ENABLED = import.meta.env.VITE_ENABLE_LIVE_API === "true";
export const LOCAL_DATA_ONLY_MODE = import.meta.env.VITE_LOCAL_DATA_ONLY !== "false";

function buildApiStatusSnapshot() {
  if (LOCAL_DATA_ONLY_MODE) {
    return {
      usingFallback: false,
      authRequired: false,
      backendUnavailable: false,
      endpoints: []
    };
  }
  const reasons = Array.from(endpointCircuitReasons.values());
  const authRequired = reasons.includes("auth");
  const backendUnavailable = reasons.includes("backend");
  return {
    usingFallback: endpointCircuitOpen.size > 0,
    authRequired,
    backendUnavailable,
    endpoints: Array.from(endpointCircuitOpen.values())
  };
}

function notifyApiStatusSubscribers() {
  const snapshot = buildApiStatusSnapshot();
  apiStatusSubscribers.forEach((callback) => {
    try {
      callback(snapshot);
    } catch {
      // Ignore subscriber errors to avoid affecting API calls.
    }
  });
}

function markEndpointCircuitOpen(breakerKey, reason) {
  if (!breakerKey) return;
  const wasOpen = endpointCircuitOpen.has(breakerKey);
  endpointCircuitOpen.add(breakerKey);
  endpointCircuitReasons.set(breakerKey, reason);
  if (!wasOpen) {
    notifyApiStatusSubscribers();
  }
}

export function getApiStatusSummary() {
  return buildApiStatusSnapshot();
}

export function subscribeApiStatus(callback) {
  if (typeof callback !== "function") {
    return () => {};
  }
  apiStatusSubscribers.add(callback);
  callback(buildApiStatusSnapshot());
  return () => {
    apiStatusSubscribers.delete(callback);
  };
}

function hasAuthToken() {
  return Boolean(readAuthToken());
}

function readAuthToken() {
  if (typeof window === "undefined") return null;
  const keys = ["access_token", "token", "authToken"];
  for (const key of keys) {
    const value = window.localStorage.getItem(key);
    if (value) return value;
  }
  return null;
}

async function parseJsonIfPossible(response) {
  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes("application/json")) {
    return null;
  }
  const text = await response.text();
  const trimmed = text.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch (err) {
    console.warn("API: Received invalid JSON payload.");
    return null;
  }
}

async function fetchJsonFromPublic(path) {
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

const publicJsonCache = new Map();

async function fetchJsonCached(path) {
  if (publicJsonCache.has(path)) {
    return publicJsonCache.get(path);
  }
  const promise = fetchJsonFromPublic(path);
  publicJsonCache.set(path, promise);
  return promise;
}

function normalizeRiskLevel(value, fallbackDepth = null) {
  const text = String(value || "").trim().toLowerCase();
  if (["critical", "severe", "high"].includes(text)) return "critical";
  if (["warning", "medium", "moderate"].includes(text)) return "warning";
  if (["safe", "low", "good"].includes(text)) return "safe";
  if (!Number.isFinite(Number(fallbackDepth))) return "warning";
  if (Number(fallbackDepth) >= 30) return "critical";
  if (Number(fallbackDepth) >= 20) return "warning";
  return "safe";
}

function titleCaseRisk(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/^\w/, (match) => match.toUpperCase());
}

function buildAlertStatus(riskLevel, anomalyFlag = false, anomalyScore = null) {
  const normalized = normalizeRiskLevel(riskLevel);
  if (anomalyFlag && normalized !== "critical") {
    if (Number.isFinite(Number(anomalyScore)) && Number(anomalyScore) >= 0.75) {
      return "critical";
    }
    return "warning";
  }
  return normalized;
}

function forecastFromAnchor(anchor, target = null, months = 3) {
  if (!Number.isFinite(Number(anchor)) && !Number.isFinite(Number(target))) {
    return [];
  }
  const base = Number.isFinite(Number(anchor)) ? Number(anchor) : Number(target);
  const next = Number.isFinite(Number(target)) ? Number(target) : base;
  const step = months > 0 ? (next - base) / months : 0;
  const now = new Date();
  const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const results = [];
  for (let index = 1; index <= months; index += 1) {
    const stamp = new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + index, 1));
    const depth = Number((base + step * index).toFixed(3));
    results.push({
      forecast_date: stamp.toISOString().slice(0, 10),
      predicted_groundwater_depth: depth,
      predicted_lower: Number((depth - 0.4).toFixed(3)),
      predicted_upper: Number((depth + 0.4).toFixed(3))
    });
  }
  return results;
}

function forecastYearlyFromAnchor(anchor, target = null, years = 2) {
  if (!Number.isFinite(Number(anchor)) && !Number.isFinite(Number(target))) {
    return [];
  }
  const base = Number.isFinite(Number(anchor)) ? Number(anchor) : Number(target);
  const next = Number.isFinite(Number(target)) ? Number(target) : base;
  const step = years > 0 ? (next - base) / years : 0;
  const now = new Date();
  const yearStart = new Date(Date.UTC(now.getUTCFullYear(), 0, 1));
  const results = [];
  for (let index = 1; index <= years; index += 1) {
    const stamp = new Date(Date.UTC(yearStart.getUTCFullYear() + index, 0, 1));
    const depth = Number((base + step * index).toFixed(3));
    results.push({
      forecast_date: stamp.toISOString().slice(0, 10),
      predicted_groundwater_depth: depth,
      predicted_lower: Number((depth - 0.8).toFixed(3)),
      predicted_upper: Number((depth + 0.8).toFixed(3))
    });
  }
  return results;
}

function observedSeriesFromFeature(feature, limit = 6) {
  const props = feature?.properties || {};
  const values = Array.isArray(props.monthly_depths_full) && props.monthly_depths_full.length
    ? props.monthly_depths_full
    : Array.isArray(props.monthly_depths) && props.monthly_depths.length
      ? props.monthly_depths
      : [];
  const labels = Array.isArray(props.monthly_depths_full_dates) && props.monthly_depths_full_dates.length
    ? props.monthly_depths_full_dates
    : Array.isArray(props.monthly_depths_dates) && props.monthly_depths_dates.length
      ? props.monthly_depths_dates
      : [];
  const series = values
    .map((value, index) => {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return null;
      return {
        label: String(labels[index] || `Month ${index + 1}`),
        groundwater_depth: Number(numeric.toFixed(3)),
        kind: "observed"
      };
    })
    .filter(Boolean);
  return limit > 0 ? series.slice(-limit) : series;
}

function computeTrendDirection(series) {
  const values = (Array.isArray(series) ? series : [])
    .map((point) => Number(point?.groundwater_depth ?? point?.predicted_groundwater_depth ?? point?.value))
    .filter((value) => Number.isFinite(value));
  if (values.length < 2) return "Stable";
  const delta = values[values.length - 1] - values[0];
  if (delta > 0.5) return "Rising";
  if (delta < -0.5) return "Falling";
  return "Stable";
}

function recommendationTextForStatus(status, anomalyFlag = false) {
  const normalized = String(status || "warning").toLowerCase();
  if (normalized === "critical") {
    return [
      "Urgent advisory: reduce pumping immediately.",
      "Adopt drip irrigation and schedule extraction by shift.",
      "Build recharge pits, farm ponds, or desilt existing tanks."
    ];
  }
  if (normalized === "warning") {
    return [
      "Monitor pumping closely over the next 90 days.",
      "Prioritize recharge pits and water-saving irrigation.",
      "Avoid new high-capacity borewells until levels stabilize."
    ];
  }
  return [
    "Continue monthly monitoring.",
    "Protect existing recharge structures.",
    "Use efficient irrigation to preserve the current balance."
  ];
}

function toFiniteNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function pickFirstTextValue(...values) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text) continue;
    const normalized = text.toLowerCase();
    if (["unknown", "na", "n/a", "null", "undefined", "-"].includes(normalized)) continue;
    return text;
  }
  return null;
}

function pickPreferredPct(mapValue, boundaryValue, rowValue) {
  const mapNumeric = toFiniteNumber(mapValue);
  const boundaryNumeric = toFiniteNumber(boundaryValue);
  const rowNumeric = toFiniteNumber(rowValue);
  if (mapNumeric !== null && mapNumeric > 0) return Number(mapNumeric.toFixed(4));
  if (boundaryNumeric !== null && boundaryNumeric > 0) return Number(boundaryNumeric.toFixed(4));
  if (rowNumeric !== null && rowNumeric > 0) return Number(rowNumeric.toFixed(4));
  if (mapNumeric !== null) return Number(mapNumeric.toFixed(4));
  if (boundaryNumeric !== null) return Number(boundaryNumeric.toFixed(4));
  if (rowNumeric !== null) return Number(rowNumeric.toFixed(4));
  return 0;
}

function readRowLulcPercent(row, key) {
  if (!row || typeof row !== "object") return null;
  const aliases = {
    water_pct: ["water_pct", "Water%", "water_2021%", "water_2021_pct"],
    trees_pct: ["trees_pct", "Trees%", "trees_2021%", "trees_2021_pct"],
    flooded_vegetation_pct: [
      "flooded_vegetation_pct",
      "flooded_vegetation_2021%",
      "flooded_vegetation_2021_pct"
    ],
    crops_pct: ["crops_pct", "Crops%", "crops_2021%", "crops_2021_pct"],
    built_area_pct: ["built_area_pct", "Built%", "built_2021%", "built_2021_pct"],
    bare_ground_pct: ["bare_ground_pct", "Bare%", "bare_2021%", "bare_2021_pct"],
    snow_ice_pct: ["snow_ice_pct", "snow_ice_2021%", "snow_ice_2021_pct"],
    clouds_pct: ["clouds_pct", "clouds_2021%", "clouds_2021_pct"],
    rangeland_pct: ["rangeland_pct", "Rangeland%", "rangeland_2021%", "rangeland_2021_pct"],
  };
  const candidates = aliases[key] || [key];
  for (const candidate of candidates) {
    const numeric = toFiniteNumber(row?.[candidate]);
    if (numeric !== null) return numeric;
  }
  return null;
}

function buildFinalRowMaps(finalRows) {
  const byId = new Map();
  const byKey = new Map();
  for (const row of finalRows) {
    if (!row || typeof row !== "object") continue;
    const district = row.District ?? row.district;
    const mandal = row.Mandal ?? row.mandal;
    const villageName = row.Village_Name ?? row.village_name ?? row.village;
    const key = buildLocationKey(district, mandal, villageName);
    const rowId = Number(row.Village_ID ?? row.village_id);
    if (Number.isFinite(rowId) && !byId.has(rowId)) {
      byId.set(rowId, row);
    }
    if (key && !byKey.has(key)) {
      byKey.set(key, row);
    }
  }
  return { byId, byKey };
}

function reconcileMapFeatureCollections(mapCollections, villageCollections, finalRows) {
  const mapByKey = new Map();
  const mapFeatures = mapCollections
    .flatMap((collection) => (Array.isArray(collection?.features) ? collection.features : []))
    .filter(Boolean);
  for (const feature of mapFeatures) {
    const props = feature?.properties || {};
    const key = buildLocationKey(props.district, props.mandal, props.village_name);
    if (key && !mapByKey.has(key)) {
      mapByKey.set(key, feature);
    }
  }

  const { byKey: rowByKey } = buildFinalRowMaps(finalRows);
  const villageFeatures = villageCollections
    .flatMap((collection) => (Array.isArray(collection?.features) ? collection.features : []))
    .filter(Boolean);
  const features = [];
  const seenKeys = new Set();
  const lulcKeys = [
    "water_pct",
    "trees_pct",
    "flooded_vegetation_pct",
    "crops_pct",
    "built_area_pct",
    "bare_ground_pct",
    "snow_ice_pct",
    "clouds_pct",
    "rangeland_pct",
  ];

  for (const villageFeature of villageFeatures) {
    const baseProps = villageFeature?.properties || {};
    const locationKey = buildLocationKey(baseProps.district, baseProps.mandal, baseProps.village_name);
    if (!locationKey || seenKeys.has(locationKey)) continue;
    seenKeys.add(locationKey);
    const mapProps = mapByKey.get(locationKey)?.properties || {};
    const row = rowByKey.get(locationKey) || {};

    const mergedProps = {
      ...baseProps,
      ...mapProps,
      village_id: baseProps.village_id,
      village_name: baseProps.village_name,
      district: baseProps.district,
      mandal: baseProps.mandal,
      state: baseProps.state ?? mapProps.state ?? row.State ?? row.state ?? "Andhra Pradesh",
      location_key: locationKey,
      soil: pickFirstTextValue(baseProps.soil, row.soil, row.Soil, mapProps.soil),
      soil_taxonomy: pickFirstTextValue(baseProps.soil_taxonomy, row.soil_taxonomy, row.Soil_Taxonomy, mapProps.soil_taxonomy),
      soil_map_unit: pickFirstTextValue(baseProps.soil_map_unit, row.soil_map_unit, row.Soil_Map_Unit, mapProps.soil_map_unit),
      dominant_crop_type: pickFirstTextValue(baseProps.dominant_crop_type, row.dominant_crop_type, mapProps.dominant_crop_type),
    };

    for (const key of lulcKeys) {
      mergedProps[key] = pickPreferredPct(
        mapProps[key],
        baseProps[key],
        readRowLulcPercent(row, key)
      );
    }

    features.push({
      type: "Feature",
      geometry: villageFeature.geometry || mapByKey.get(locationKey)?.geometry || null,
      properties: mergedProps
    });
  }

  for (const mapFeature of mapFeatures) {
    const props = mapFeature?.properties || {};
    const key = buildLocationKey(props.district, props.mandal, props.village_name);
    if (!key || seenKeys.has(key)) continue;
    seenKeys.add(key);
    features.push(mapFeature);
  }

  return { type: "FeatureCollection", features };
}

let alignedLocalDataPromise = null;

async function getAlignedLocalData() {
  if (alignedLocalDataPromise) return alignedLocalDataPromise;
  alignedLocalDataPromise = (async () => {
    const [mapData, mapDataNtr, villageData, villageDataNtr, finalData, finalDatasetNtr] = await Promise.all([
      fetchJsonCached("/data/map_data_predictions.geojson"),
      fetchJsonCached("/data/map_data_predictions_ntr.geojson"),
      fetchJsonCached("/data/villages.geojson"),
      fetchJsonCached("/data/villages_ntr.geojson"),
      fetchJsonCached("/data/final_dataset.json"),
      fetchJsonCached("/data/final_dataset_ntr.json")
    ]);
    const finalRows = [
      ...(Array.isArray(finalData) ? finalData : []),
      ...(Array.isArray(finalDatasetNtr) ? finalDatasetNtr : [])
    ].filter((row) => row && typeof row === "object");
    const mapCollection = reconcileMapFeatureCollections(
      [mapData, mapDataNtr],
      [villageData, villageDataNtr],
      finalRows
    );
    return { mapCollection, finalRows };
  })();
  return alignedLocalDataPromise;
}

async function findLocalVillageFeature(villageId) {
  const numericVillageId = Number(villageId);
  const { mapCollection, finalRows } = await getAlignedLocalData();

  const featureById = new Map();
  const featureByKey = new Map();
  const features = Array.isArray(mapCollection?.features) ? mapCollection.features : [];
  for (const feature of features) {
    const props = feature?.properties || {};
    const featureId = Number(props.village_id);
    const featureKey = buildLocationKey(props.district, props.mandal, props.village_name);
    if (Number.isFinite(featureId) && !featureById.has(featureId)) {
      featureById.set(featureId, feature);
    }
    if (featureKey && !featureByKey.has(featureKey)) {
      featureByKey.set(featureKey, feature);
    }
  }

  const { byId: rowById, byKey: rowByKey } = buildFinalRowMaps(finalRows);

  const row = rowById.get(numericVillageId) || null;
  const idFeature = Number.isFinite(numericVillageId) ? featureById.get(numericVillageId) : null;
  const idFeatureKey = buildLocationKey(
    idFeature?.properties?.district,
    idFeature?.properties?.mandal,
    idFeature?.properties?.village_name
  );
  const resolvedRow = (idFeatureKey && rowByKey.get(idFeatureKey)) || row;
  const rowKey = buildLocationKey(
    resolvedRow?.District ?? resolvedRow?.district,
    resolvedRow?.Mandal ?? resolvedRow?.mandal,
    resolvedRow?.Village_Name ?? resolvedRow?.village_name ?? resolvedRow?.village
  );
  const matchedFeature = idFeature || (rowKey && featureByKey.get(rowKey)) || null;
  if (matchedFeature) return matchedFeature;
  if (!resolvedRow) return null;

  return {
    type: "Feature",
    geometry: null,
    properties: {
      village_id: resolvedRow.Village_ID ?? resolvedRow.village_id,
      village_name: resolvedRow.Village_Name ?? resolvedRow.village_name ?? resolvedRow.village,
      district: resolvedRow.District ?? resolvedRow.district,
      mandal: resolvedRow.Mandal ?? resolvedRow.mandal,
      location_key: rowKey,
      actual_last_month: resolvedRow.actual_last_month ?? resolvedRow.GW_Level,
      long_term_avg: resolvedRow.long_term_avg,
      monthly_depths: resolvedRow.monthly_depths,
      monthly_depths_dates: resolvedRow.monthly_depths_dates,
      monthly_depths_full: resolvedRow.monthly_depths_full,
      monthly_depths_full_dates: resolvedRow.monthly_depths_full_dates,
      predicted_groundwater_level: resolvedRow.GW_Level,
      risk_level: resolvedRow.risk_level,
      confidence: resolvedRow.confidence_score
    }
  };
}

function mergeFeatureCollections(collections) {
  const byLocation = new Map();
  const byVillageId = new Map();
  for (const collection of collections) {
    const features = Array.isArray(collection?.features) ? collection.features : [];
    for (const feature of features) {
      const props = feature?.properties || {};
      const villageId = Number(props.village_id);
      const key = buildLocationKey(props.district, props.mandal, props.village_name);
      if (Number.isFinite(villageId) && !byVillageId.has(villageId)) {
        byVillageId.set(villageId, feature);
      }
      if (key && !byLocation.has(key)) {
        byLocation.set(key, feature);
      }
    }
  }
  return {
    type: "FeatureCollection",
    features: Array.from(byLocation.values()).concat(
      Array.from(byVillageId.entries())
        .filter(([id]) => !Array.from(byLocation.values()).some((feature) => Number(feature?.properties?.village_id) === id))
        .map(([, feature]) => feature)
    )
  };
}

async function buildVillageForecastFallback(villageId) {
  const feature = await findLocalVillageFeature(villageId);
  if (!feature) return null;
  const props = feature.properties || {};
  const observedSeries = observedSeriesFromFeature(feature, 6);
  const currentDepth = Number(
    props.actual_last_month ??
    props.depth ??
    props.predicted_groundwater_level ??
    props.GW_Level
  );
  const forecastAnchor = Number.isFinite(Number(props.forecast_3m))
    ? Number(props.forecast_3m)
    : Number.isFinite(Number(props.predicted_groundwater_level))
      ? Number(props.predicted_groundwater_level)
      : currentDepth;
  const forecast_3_month = Array.isArray(props.forecast_3_month) && props.forecast_3_month.length
    ? props.forecast_3_month
    : forecastFromAnchor(currentDepth, forecastAnchor, 3);
  const forecast_yearly = Array.isArray(props.forecast_yearly) && props.forecast_yearly.length
    ? props.forecast_yearly
    : forecastYearlyFromAnchor(currentDepth, forecastAnchor, 2);
  const predictedDepth = Number.isFinite(Number(props.predicted_groundwater_level))
    ? Number(props.predicted_groundwater_level)
    : Number.isFinite(Number(forecastAnchor))
      ? Number(forecastAnchor)
      : Number.isFinite(Number(currentDepth))
        ? Number(currentDepth)
        : null;
  const riskLevel = titleCaseRisk(normalizeRiskLevel(props.risk_level, currentDepth));
  const alertStatus = buildAlertStatus(riskLevel, Boolean(props.anomaly_flag));
  return {
    village_id: Number(props.village_id),
    village_name: props.village_name || "Unknown",
    district: props.district || "",
    mandal: props.mandal || "",
    model_name: "krishna-fallback-model",
    mode: "batch_fallback",
    current_depth: Number.isFinite(Number(currentDepth)) ? Number(currentDepth) : null,
    predicted_groundwater_level: Number.isFinite(Number(predictedDepth)) ? Number(predictedDepth) : null,
    confidence_score: Number.isFinite(Number(props.confidence_score ?? props.confidence))
      ? Number(props.confidence_score ?? props.confidence)
      : 0,
    risk_level: riskLevel,
    alert_status: alertStatus,
    anomaly_flag: Boolean(props.anomaly_flag),
    anomaly_score: Number.isFinite(Number(props.anomaly_score)) ? Number(props.anomaly_score) : null,
    anomaly_type: props.anomaly_type || null,
    trend_direction: computeTrendDirection(observedSeries),
    observed_series: observedSeries,
    forecast_3_month,
    forecast_yearly,
    recommended_actions: recommendationTextForStatus(alertStatus, Boolean(props.anomaly_flag)),
  };
}

async function buildVillageStatusFallback(villageId) {
  const forecast = await buildVillageForecastFallback(villageId);
  if (!forecast) return null;
  return {
    village_id: forecast.village_id,
    current_depth: forecast.observed_series.length
      ? forecast.observed_series[forecast.observed_series.length - 1].groundwater_depth
      : forecast.current_depth,
    forecast_3_month: forecast.forecast_3_month,
    forecast_yearly: forecast.forecast_yearly,
    anomaly_flags: [
      `Risk level: ${forecast.risk_level}`,
      ...(forecast.alert_status === "critical" ? ["Urgent advisory required"] : []),
    ],
    confidence_score: forecast.confidence_score,
    risk_level: forecast.risk_level,
    alert_status: forecast.alert_status,
    trend_direction: forecast.trend_direction,
    recommended_actions: forecast.recommended_actions,
    observed_series: forecast.observed_series
  };
}

async function buildRechargeFallback() {
  const mapData = await fetchJsonCached("/data/map_data_predictions.geojson");
  const features = Array.isArray(mapData?.features) ? mapData.features : [];
  return {
    type: "FeatureCollection",
    features: features
      .map((feature) => {
        const props = feature?.properties || {};
        const score = Number(props.recharge_index ?? props.infiltration_score ?? 0);
        const riskLevel = titleCaseRisk(normalizeRiskLevel(props.risk_level, props.predicted_groundwater_level));
        return {
          type: "Feature",
          geometry: feature.geometry,
          properties: {
            village_id: props.village_id,
            village_name: props.village_name,
            district: props.district,
            mandal: props.mandal,
            score: Number.isFinite(score) ? Number(score.toFixed(4)) : 0,
            groundwater_depth: Number(props.predicted_groundwater_level ?? props.depth ?? 0),
            risk_level: riskLevel,
            confidence_score: Number(props.confidence ?? 0),
            reason: "Recharge candidate from permeability and stress indicators",
            recommendation: "Prefer recharge pits, farm ponds, and staggered pumping."
          }
        };
      })
      .sort((a, b) => (b.properties.score || 0) - (a.properties.score || 0))
      .slice(0, 300)
  };
}

async function buildAnomalyFallback(outputFormat = "json", limit = 500) {
  const anomalies = await fetchJsonCached("/data/anomalies_krishna.json");
  const features = Array.isArray(anomalies?.features) ? anomalies.features.slice(0, limit) : [];
  if (outputFormat === "geojson") {
    return { type: "FeatureCollection", features };
  }
  return features
    .map((feature) => {
      const props = feature?.properties || {};
      return {
        village_id: Number(props.village_id),
        anomaly_type: String(props.anomaly_type || props.type || props.severity || "Unknown"),
        anomaly_score: Number.isFinite(Number(props.anomaly_score ?? props.deviation_m))
          ? Number(props.anomaly_score ?? props.deviation_m)
          : null,
        detected_at: String(props.detected_at || new Date().toISOString()),
        alert_level: buildAlertStatus("warning", true, Number(props.anomaly_score ?? props.deviation_m)),
        recommendation: "Inspect the village immediately and compare with pumping and sensor records."
      };
    })
    .filter((row) => Number.isFinite(Number(row.village_id)));
}

const fetchSafe = async (url, defaultValue = null, options = {}) => {
  const { auth = false, init = {}, breakerKey = null, live = true } = options;
  if (!live) {
    if (!LOCAL_DATA_ONLY_MODE) {
      markEndpointCircuitOpen(breakerKey, "backend");
    }
    return defaultValue;
  }

  if (breakerKey && endpointCircuitOpen.has(breakerKey)) {
    return defaultValue;
  }

  if (auth && !hasAuthToken()) {
    markEndpointCircuitOpen(breakerKey, "auth");
    return defaultValue;
  }

  try {
    const headers = new Headers(init.headers || {});
    if (auth) {
      const token = readAuthToken();
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
    }

    const res = await fetch(url, { ...init, headers });
    if (!res.ok) {
      if (res.status >= 500) {
        markEndpointCircuitOpen(breakerKey, "backend");
      }
      if (res.status === 401 || res.status === 403) {
        markEndpointCircuitOpen(breakerKey, "auth");
      }
      if (res.status !== 401 && res.status !== 403) {
        console.warn(`API: ${res.status} on ${url} - using fallback data`);
      }
      return defaultValue;
    }

    const data = await parseJsonIfPossible(res);
    return data ?? defaultValue;
  } catch (err) {
    return defaultValue;
  }
};

export const api = {
  getPrediction: async (villageId, options = {}) => {
    const mode = String(options.mode || "batch").toLowerCase() === "live" ? "live" : "batch";
    const asOf = options.asOf ? `&as_of=${encodeURIComponent(options.asOf)}` : "";
    const remote = await fetchSafe(
      `${API_BASE}/predict?village_id=${encodeURIComponent(villageId)}&mode=${mode}${asOf}`,
      null,
      { breakerKey: "predict", live: LIVE_API_ENABLED }
    );
    if (remote && Number.isFinite(Number(remote.village_id))) return remote;
    return (await buildVillageForecastFallback(villageId)) || null;
  },

  getStGnnPrediction: async (villageId) => {
    const remote = await fetchSafe(
      `${API_BASE}/predictions/st-gnn/village/${villageId}`,
      null,
      { breakerKey: "stGnnPredict", live: LIVE_API_ENABLED }
    );
    return remote;
  },

  getMapData: async () => {
    const remote = await fetchSafe(
      `${API_BASE}/map-data`,
      null,
      { breakerKey: "mapData", live: LIVE_API_ENABLED }
    );
    if (remote && Array.isArray(remote.features)) return remote;
    const [krishna, ntr] = await Promise.all([
      fetchJsonCached("/data/map_data_predictions.geojson"),
      fetchJsonCached("/data/map_data_predictions_ntr.geojson"),
    ]);
    if (krishna || ntr) {
      const { mapCollection } = await getAlignedLocalData();
      return mapCollection;
    }
    return { type: "FeatureCollection", features: [] };
  },

  getRechargeRecommendations: async () => {
    const remote = await fetchSafe(
      `${API_BASE}/recharge-recommendations`,
      null,
      { breakerKey: "rechargeRecommendations", live: LIVE_API_ENABLED }
    );
    if (remote && Array.isArray(remote.features)) return remote;
    return (await buildRechargeFallback()) || { type: "FeatureCollection", features: [] };
  },

  getVillageStatus: async (villageId) => {
    const remote = await fetchSafe(
      `${API_BASE}/get-village-status/${villageId}`,
      null,
      { breakerKey: "villageStatus", live: LIVE_API_ENABLED }
    );
    if (remote && Number.isFinite(Number(remote.village_id))) return remote;
    return (await buildVillageStatusFallback(villageId)) || {
      village_id: Number(villageId),
      current_depth: null,
      forecast_3_month: [],
      forecast_yearly: [],
      anomaly_flags: [],
      confidence_score: 0,
      risk_level: "Warning",
      alert_status: "warning",
      trend_direction: "Stable",
      recommended_actions: []
    };
  },

  getVillageForecast: async (villageId) => {
    const remote = await fetchSafe(
      `${API_BASE}/village/${villageId}/forecast`,
      null,
      { auth: true, breakerKey: "villageForecast", live: LIVE_API_ENABLED }
    );
    if (remote && Number.isFinite(Number(remote.village_id))) return remote;
    return (await buildVillageForecastFallback(villageId)) || {
      village_id: Number(villageId),
      model_name: "krishna-fallback-model",
      observed_series: [],
      forecast_3_month: [],
      forecast_yearly: [],
      confidence_score: 0,
      risk_level: "Warning",
      alert_status: "warning",
      trend_direction: "Stable",
      recommended_actions: []
    };
  },

  getAnomalies: async (outputFormat = "geojson") => {
    const remote = await fetchSafe(
      `${API_BASE}/alerts/anomalies?output_format=${outputFormat}`,
      null,
      { auth: false, breakerKey: "anomalies", live: LIVE_API_ENABLED }
    );
    if (remote) return remote;
    return await buildAnomalyFallback(outputFormat, 500);
  },

  locateVillage: (lat, lon) => 
    fetchSafe(`${API_BASE}/village/locate?lat=${lat}&lon=${lon}`, null),
  
  getFarmerAdvisories: (villageId) => {
    const url = villageId 
      ? `${API_BASE}/farmer-advisories?village_id=${villageId}` 
      : `${API_BASE}/farmer-advisories`;
    return fetchSafe(url, { 
      advisories: [
        { village_id: 1, advisory_level: "Warning", advisory_text: "Switch to micro-irrigation for next 30 days.", generated_at: new Date().toISOString() }
      ] 
    }, { auth: true, breakerKey: "farmerAdvisories", live: LIVE_API_ENABLED });
  }
};
