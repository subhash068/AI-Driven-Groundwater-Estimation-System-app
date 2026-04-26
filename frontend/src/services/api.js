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
  getRechargeRecommendations: () => 
    fetchSafe(`${API_BASE}/recharge-recommendations`, { 
      type: "FeatureCollection", 
      features: [
        { type: "Feature", geometry: { type: "Point", coordinates: [80.64, 16.50] }, properties: { score: 0.85, reason: "High permeability alluvium" } },
        { type: "Feature", geometry: { type: "Point", coordinates: [79.98, 15.60] }, properties: { score: 0.72, reason: "Draft-to-recharge deficit" } }
      ] 
    }, { breakerKey: "rechargeRecommendations", live: LIVE_API_ENABLED }),
  
  getVillageStatus: (villageId) => 
    fetchSafe(`${API_BASE}/get-village-status/${villageId}`, { 
      current_depth: 12.5, 
      forecast_3_month: [], 
      anomaly_flags: ["Historical Deviation"],
      confidence_score: 0.88
    }, { breakerKey: "villageStatus", live: LIVE_API_ENABLED }),
  
  getVillageForecast: (villageId) => 
    fetchSafe(`${API_BASE}/village/${villageId}/forecast`, { 
      forecast_3_month: [
        { forecast_date: "2024-05-01", predicted_groundwater_depth: 13.2 },
        { forecast_date: "2024-06-01", predicted_groundwater_depth: 14.5 },
        { forecast_date: "2024-07-01", predicted_groundwater_depth: 15.8 }
      ] 
    }, { auth: true, breakerKey: "villageForecast", live: LIVE_API_ENABLED }),
  
  getAnomalies: async (outputFormat = "geojson") => {
    const remote = await fetchSafe(
      `${API_BASE}/alerts/anomalies?output_format=${outputFormat}`,
      null,
      { auth: false, breakerKey: "anomalies", live: LIVE_API_ENABLED }
    );
    if (remote) return remote;
    if (outputFormat === "geojson") {
      const local = await fetchJsonFromPublic("/data/anomalies_krishna.json");
      if (local) return local;
      return { type: "FeatureCollection", features: [] };
    }
    return { alerts: [] };
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
