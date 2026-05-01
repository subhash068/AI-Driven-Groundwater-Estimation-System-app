const API_BASE_URL =
  (typeof import.meta !== "undefined" &&
    import.meta?.env?.VITE_API_BASE_URL) ||
  "http://127.0.0.1:8000";

export const LOCAL_DATA_ONLY_MODE = false;

const apiStatusState = {
  usingFallback: false,
  authRequired: false,
  backendUnavailable: false
};

const apiStatusListeners = new Set();

function emitApiStatus() {
  const snapshot = { ...apiStatusState };
  apiStatusListeners.forEach((listener) => {
    try {
      listener(snapshot);
    } catch {
      // ignore listener errors
    }
  });
}

function setStatusPatch(patch) {
  Object.assign(apiStatusState, patch);
  emitApiStatus();
}

function getAuthToken() {
  try {
    return (
      window?.localStorage?.getItem("access_token") ||
      window?.localStorage?.getItem("token") ||
      ""
    );
  } catch {
    return "";
  }
}

async function requestJson(path, options = {}) {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    }
  });

  if (response.status === 401 || response.status === 403) {
    setStatusPatch({ usingFallback: true, authRequired: true });
    throw new Error("Authentication required");
  }

  if (!response.ok) {
    if (response.status >= 500 || response.status === 0) {
      setStatusPatch({ usingFallback: true, backendUnavailable: true });
    }
    throw new Error(`API request failed: ${response.status}`);
  }

  setStatusPatch({
    usingFallback: false,
    authRequired: false,
    backendUnavailable: false
  });
  return response.json();
}

async function readGeoJsonFallback(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`Fallback file missing: ${path}`);
  const payload = await res.json();
  if (payload?.type === "FeatureCollection") return payload;
  return { type: "FeatureCollection", features: [] };
}

function featureCollectionToList(collection) {
  const features = Array.isArray(collection?.features) ? collection.features : [];
  return features.map((feature) => {
    const props = feature?.properties || {};
    return {
      village_id: Number(props.village_id),
      anomaly_type: props.anomaly_type || (props.is_anomaly ? "Detected" : "Normal"),
      anomaly_score: Number(props.anomaly_score ?? 0),
      detected_at: props.detected_at || null
    };
  });
}

export function getApiStatusSummary() {
  return { ...apiStatusState };
}

export function subscribeApiStatus(listener) {
  if (typeof listener !== "function") return () => {};
  apiStatusListeners.add(listener);
  listener({ ...apiStatusState });
  return () => apiStatusListeners.delete(listener);
}

export const api = {
  async getMapData() {
    if (LOCAL_DATA_ONLY_MODE) {
      return readGeoJsonFallback("/data/map_data_predictions.geojson");
    }
    try {
      return await requestJson("/api/groundwater/all");
    } catch {
      setStatusPatch({ usingFallback: true });
      try {
        return await requestJson("/map-data");
      } catch {
        return readGeoJsonFallback("/data/map_data_predictions.geojson");
      }
    }
  },

  async getAnomalies(outputFormat = "geojson") {
    const wantsJson = String(outputFormat).toLowerCase() === "json";
    if (LOCAL_DATA_ONLY_MODE) {
      const fallback = await readGeoJsonFallback("/data/anomalies_krishna.json");
      return wantsJson ? featureCollectionToList(fallback) : fallback;
    }
    try {
      const payload = await requestJson("/api/groundwater/anomalies");
      return wantsJson ? featureCollectionToList(payload) : payload;
    } catch {
      setStatusPatch({ usingFallback: true });
      try {
        const legacy = await requestJson(`/alerts/anomalies?output_format=${wantsJson ? "json" : "geojson"}`);
        if (wantsJson && Array.isArray(legacy?.alerts)) return legacy.alerts;
        return legacy;
      } catch {
        const fallback = await readGeoJsonFallback("/data/anomalies_krishna.json");
        return wantsJson ? featureCollectionToList(fallback) : fallback;
      }
    }
  },

  async getRechargeRecommendations() {
    if (LOCAL_DATA_ONLY_MODE) {
      return { type: "FeatureCollection", features: [] };
    }
    try {
      return await requestJson("/api/groundwater/recharge");
    } catch {
      setStatusPatch({ usingFallback: true });
      try {
        return await requestJson("/recharge-recommendations");
      } catch {
        return { type: "FeatureCollection", features: [] };
      }
    }
  },

  async getVillageStatus(villageId) {
    return requestJson(`/get-village-status/${Number(villageId)}`);
  },

  async getPrediction(villageId, options = {}) {
    const mode = String(options.mode || "batch");
    return requestJson(`/predict?village_id=${Number(villageId)}&mode=${encodeURIComponent(mode)}`);
  },

  async getVillageForecast(villageId) {
    return requestJson(`/village/${Number(villageId)}/forecast`);
  },

  async getStGnnPrediction(villageId) {
    try {
      return await requestJson(`/api/groundwater/${Number(villageId)}`);
    } catch {
      return requestJson(`/api/predictions/st-gnn/village/${Number(villageId)}`);
    }
  },

  async simulateGroundwater(payload) {
    return requestJson("/api/groundwater/simulate", {
      method: "POST",
      body: JSON.stringify(payload || {})
    });
  },

  async getModelUpgradeSummary() {
    try {
      return await requestJson("/analytics/model-upgrades");
    } catch {
      return null;
    }
  }
};
