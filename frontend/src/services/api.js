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
  if (payload && Array.isArray(payload.features)) {
    return { ...payload, type: "FeatureCollection" };
  }
  return { type: "FeatureCollection", features: [] };
}

async function getLocalVillageFeature(villageId) {
  const numericId = Number(villageId);
  const sources = [
    "/data/map_data_predictions.geojson",
    "/data/map_data_predictions_ntr.geojson"
  ];
  for (const path of sources) {
    try {
      const payload = await readGeoJsonFallback(path);
      const features = Array.isArray(payload?.features) ? payload.features : [];
      const match = features.find(
        (feature) => Number(feature?.properties?.village_id) === numericId
      );
      if (match) return match;
    } catch {
      // try next source
    }
  }
  return null;
}

function toNumberOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
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
    if (LOCAL_DATA_ONLY_MODE) return readGeoJsonFallback("/data/map_data_predictions.geojson");
    return requestJson("/v2/map-data");
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
    if (LOCAL_DATA_ONLY_MODE) {
      const feature = await getLocalVillageFeature(villageId);
      const props = feature?.properties || {};
      return {
        village_id: Number(villageId),
        current_depth:
          toNumberOrNull(props.current_depth) ??
          toNumberOrNull(props.predicted_groundwater_level) ??
          toNumberOrNull(props.depth),
        confidence_score:
          toNumberOrNull(props.confidence_score) ??
          toNumberOrNull(props.confidence) ??
          0,
        anomaly_flags: Array.isArray(props.anomaly_flags) ? props.anomaly_flags : [],
        forecast_3_month: Array.isArray(props.forecast_3_month) ? props.forecast_3_month : [],
        observed_series: Array.isArray(props.observed_series) ? props.observed_series : [],
        trend_direction: props.trend_direction || props.trend || "Stable",
        risk_level: props.risk_level || "warning",
        recommended_actions: Array.isArray(props.recommended_actions) ? props.recommended_actions : [],
        // Preserve monthly series
        monthly_rainfall: props.monthly_rainfall || props.normalized_monthly_rainfall || [],
        monthly_recharge: props.monthly_recharge || props.normalized_monthly_recharge || [],
        monthly_predicted_gw: props.monthly_predicted_gw || props.normalized_monthly_predicted || [],
        monthly_actual_gw: props.monthly_actual_gw || props.normalized_monthly_depths || [],
        monthly_dates: props.monthly_dates || props.normalized_monthly_dates || []
      };
    }
    return requestJson(`/get-village-status/${Number(villageId)}`);
  },

  async getPrediction(villageId, options = {}) {
    if (LOCAL_DATA_ONLY_MODE) {
      const feature = await getLocalVillageFeature(villageId);
      const props = feature?.properties || {};
      return {
        village_id: Number(villageId),
        predicted_groundwater_level:
          toNumberOrNull(props.predicted_groundwater_level) ??
          toNumberOrNull(props.groundwater_estimate) ??
          toNumberOrNull(props.depth),
        confidence_score:
          toNumberOrNull(props.confidence_score) ??
          toNumberOrNull(props.confidence) ??
          0,
        risk_level: props.risk_level || "warning",
        draft_index: toNumberOrNull(props.draft_index) ?? 0,
        forecast_3_month: Array.isArray(props.forecast_3_month) ? props.forecast_3_month : [],
        forecast_yearly: Array.isArray(props.forecast_yearly) ? props.forecast_yearly : [],
        observed_series: Array.isArray(props.observed_series) ? props.observed_series : [],
        recommended_actions: Array.isArray(props.recommended_actions) ? props.recommended_actions : [],
        anomaly_flag: Boolean(props.anomaly_flag),
        anomaly_score: toNumberOrNull(props.anomaly_score) ?? 0,
        // Include monthly series for consistency and chart support
        monthly_rainfall: props.monthly_rainfall || props.normalized_monthly_rainfall || [],
        monthly_recharge: props.monthly_recharge || props.normalized_monthly_recharge || [],
        monthly_predicted_gw: props.monthly_predicted_gw || props.normalized_monthly_predicted || [],
        monthly_actual_gw: props.monthly_actual_gw || props.normalized_monthly_depths || [],
        monthly_dates: props.monthly_dates || props.normalized_monthly_dates || [],
        mode: "local"
      };
    }
    // Always use V2 for live predictions
    const data = await requestJson(`/v2/predict?village_id=${Number(villageId)}`);
    return {
      ...data,
      predicted_groundwater_level: data.predicted_groundwater_level ?? data.groundwater_level,
      confidence_score: data.confidence_score ?? data.confidence
    };
  },

  async getVillageForecast(villageId) {
    if (LOCAL_DATA_ONLY_MODE) {
      const feature = await getLocalVillageFeature(villageId);
      const props = feature?.properties || {};
      return {
        village_id: Number(villageId),
        model_name: props.model_name || "local-static",
        risk_level: props.risk_level || "warning",
        forecast_3_month: Array.isArray(props.forecast_3_month) ? props.forecast_3_month : [],
        forecast_yearly: Array.isArray(props.forecast_yearly) ? props.forecast_yearly : []
      };
    }
    return requestJson(`/village/${Number(villageId)}/forecast`);
  },

  async getStGnnPrediction(villageId) {
    if (LOCAL_DATA_ONLY_MODE) {
      const feature = await getLocalVillageFeature(villageId);
      return feature?.properties || {
        village_id: Number(villageId),
        groundwater_level: null
      };
    }
    try {
      return await requestJson(`/api/groundwater/${Number(villageId)}`);
    } catch {
      return requestJson(`/api/predictions/st-gnn/village/${Number(villageId)}`);
    }
  },

  async simulateGroundwater(payload) {
    if (LOCAL_DATA_ONLY_MODE) {
      return { type: "FeatureCollection", features: [] };
    }
    const villageId = payload.village_id;
    const url = villageId 
      ? `/api/groundwater/village/${villageId}/simulate` 
      : "/api/groundwater/simulate";
      
    return requestJson(url, {
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
  },

  async getLulcTrends(villageId) {
    if (LOCAL_DATA_ONLY_MODE) return null;
    return requestJson(`/v2/lulc-trends?village_id=${Number(villageId)}`);
  },

  async retrain() {
    if (LOCAL_DATA_ONLY_MODE) return { status: "local-only" };
    return requestJson("/v2/retrain", { method: "POST" });
  },

  async login(username, password) {
    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);

    const response = await fetch(`${API_BASE_URL}/auth/token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(error.detail || "Login failed");
    }

    const data = await response.json();
    localStorage.setItem("access_token", data.access_token);
    setStatusPatch({ authRequired: false });
    return data;
  },

  logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("token");
    setStatusPatch({ authRequired: false });
    window.location.reload();
  }
};
