const API_BASE = import.meta.env.VITE_API_BASE || "/api";
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

async function findLocalVillageFeature(villageId) {
  const numericVillageId = Number(villageId);
  const [mapData, villageData, finalData] = await Promise.all([
    fetchJsonCached("/data/map_data_predictions.geojson"),
    fetchJsonCached("/data/villages.geojson"),
    fetchJsonCached("/data/final_dataset.json")
  ]);
  const finalDatasetNtr = await fetchJsonCached("/data/final_dataset_ntr.json");

  const searchCollections = [
    Array.isArray(mapData?.features) ? mapData.features : [],
    Array.isArray(villageData?.features) ? villageData.features : []
  ];
  for (const collection of searchCollections) {
    const match = collection.find((feature) => Number(feature?.properties?.village_id) === numericVillageId);
    if (match) return match;
  }

  const fallbackRow = Array.isArray(finalData)
    ? finalData.find((row) => Number(row?.Village_ID) === numericVillageId)
    : null;
  const fallbackRowNtr = Array.isArray(finalDatasetNtr)
    ? finalDatasetNtr.find((row) => Number(row?.Village_ID) === numericVillageId)
    : null;
  const row = fallbackRow || fallbackRowNtr;
  if (!row) return null;

  return {
    type: "Feature",
    geometry: null,
    properties: {
      village_id: row.Village_ID,
      village_name: row.Village_Name,
      district: row.District,
      mandal: row.Mandal,
      actual_last_month: row.actual_last_month ?? row.GW_Level,
      long_term_avg: row.long_term_avg,
      monthly_depths: row.monthly_depths,
      monthly_depths_dates: row.monthly_depths_dates,
      monthly_depths_full: row.monthly_depths_full,
      monthly_depths_full_dates: row.monthly_depths_full_dates,
      predicted_groundwater_level: row.GW_Level,
      risk_level: row.risk_level,
      confidence: row.confidence_score
    }
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
  const riskLevel = titleCaseRisk(normalizeRiskLevel(props.risk_level, currentDepth));
  const alertStatus = buildAlertStatus(riskLevel, Boolean(props.anomaly_flag));
  return {
    village_id: Number(props.village_id),
    village_name: props.village_name || "Unknown",
    district: props.district || "",
    mandal: props.mandal || "",
    model_name: "krishna-fallback-model",
    confidence_score: Number.isFinite(Number(props.confidence_score ?? props.confidence))
      ? Number(props.confidence_score ?? props.confidence)
      : 0,
    risk_level: riskLevel,
    alert_status: alertStatus,
    trend_direction: computeTrendDirection(observedSeries),
    observed_series: observedSeries,
    forecast_3_month,
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
      : null,
    forecast_3_month: forecast.forecast_3_month,
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
  getMapData: async () => {
    const remote = await fetchSafe(
      `${API_BASE}/map-data`,
      null,
      { breakerKey: "mapData", live: LIVE_API_ENABLED }
    );
    if (remote && Array.isArray(remote.features)) return remote;
    const local = await fetchJsonCached("/data/map_data_predictions.geojson");
    return local || { type: "FeatureCollection", features: [] };
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
