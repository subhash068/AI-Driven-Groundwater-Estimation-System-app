import L from "leaflet";
import { buildDistrictVillageKey, normalizeDistrictVillageKeyPart } from "./key";

export function normalizeLocationName(value) {
  return normalizeDistrictVillageKeyPart(value);
}

export function buildLocationKey(district, mandal, villageName = "") {
  return buildDistrictVillageKey(district, mandal, villageName);
}

export function geometryCenter(geometry) {
  if (!geometry) return { longitude: 79.74, latitude: 15.91 };
  let coords = [];
  if (geometry.type === "Polygon") {
    coords = geometry.coordinates[0] || [];
  } else if (geometry.type === "MultiPolygon") {
    coords = (geometry.coordinates[0] || [])[0] || [];
  } else if (geometry.type === "Point") {
    const [lon, lat] = geometry.coordinates;
    return { longitude: lon, latitude: lat };
  }
  if (!coords.length) return { longitude: 79.74, latitude: 15.91 };
  const sum = coords.reduce((acc, [lon, lat]) => ({ lon: acc.lon + lon, lat: acc.lat + lat }), {
    lon: 0,
    lat: 0
  });
  return { longitude: sum.lon / coords.length, latitude: sum.lat / coords.length };
}

export function healthColor(depth) {
  if (depth >= 30) return [190, 38, 38, 180]; // critical: red
  if (depth >= 20) return [217, 160, 52, 175]; // warning
  return [52, 146, 70, 175]; // safe: green
}

export function advisoryLabel(depth) {
  if (depth >= 30) return "Critical";
  if (depth >= 20) return "Warning";
  return "Safe";
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function pointInRing(point, ring) {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / ((yj - yi) || Number.EPSILON) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInPolygon(point, polygonCoords) {
  if (!Array.isArray(polygonCoords) || !polygonCoords.length) return false;
  const [outerRing, ...holes] = polygonCoords;
  if (!outerRing || !pointInRing(point, outerRing)) return false;
  return !holes.some((hole) => pointInRing(point, hole));
}

export function pointInGeometry(point, geometry) {
  if (!point || !geometry) return false;
  if (geometry.type === "Polygon") {
    return pointInPolygon(point, geometry.coordinates);
  }
  if (geometry.type === "MultiPolygon") {
    return (geometry.coordinates || []).some((polygon) => pointInPolygon(point, polygon));
  }
  return false;
}

function shiftRingFor3D(ring, depthFactor) {
  const lonShift = 0.00005 * depthFactor;
  const latShift = -0.000035 * depthFactor;
  return ring.map(([lon, lat]) => [lon + lonShift, lat + latShift]);
}

export function shiftGeometryFor3D(geometry, depthFactor) {
  if (!geometry) return null;
  if (geometry.type === "Polygon") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((ring) => shiftRingFor3D(ring, depthFactor))
    };
  }
  if (geometry.type === "MultiPolygon") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((poly) =>
        poly.map((ring) => shiftRingFor3D(ring, depthFactor))
      )
    };
  }
  return geometry;
}

/**
 * Normalizes village properties to ensure consistent naming and prevent 'NA' displays.
 * Centralizes the complex fallback logic for depths, risks, and confidence scores.
 */
export function normalizeVillageProperties(props) {
  if (!props) return null;

  // 1. Depth Normalization (Priority: Actual > Predicted > Legacy > Static)
  const depthCandidates = [
    props.current_depth,
    props.actual_last_month,
    props.target_last_month,
    props.gw_level,
    props.GW_Level,
    props.depth,
    props.predicted_groundwater_level,
    props.groundwater_estimate
  ];
  
  const currentDepthRaw = depthCandidates.find(v => v !== null && v !== undefined && String(v).trim() !== "" && Number.isFinite(Number(v)));
  const currentDepth = currentDepthRaw !== undefined ? Number(currentDepthRaw) : null;
  
  // 2. Risk Normalization (Critical/Warning/Safe)
  let risk = String(props.risk_level || "").trim().toLowerCase();
  if (!["critical", "warning", "safe", "high", "medium", "low"].includes(risk)) {
    // If risk is missing or invalid, derive from depth
    if (currentDepth !== null) {
      if (currentDepth >= 30) risk = "critical";
      else if (currentDepth >= 20) risk = "warning";
      else risk = "safe";
    } else {
      risk = "safe";
    }
  }
  
  // Map Aliases
  if (risk === "high") risk = "critical";
  if (risk === "medium" || risk === "moderate") risk = "warning";
  if (risk === "low") risk = "safe";

  // 4. Series Normalization (Map various names to a standard set)
  const getSeries = (...candidates) => {
    for (const c of candidates) {
      if (Array.isArray(c) && c.length > 0) return c;
      if (typeof c === 'string' && c.startsWith('[') && c.length > 2) {
        try {
          const parsed = JSON.parse(c);
          if (Array.isArray(parsed) && parsed.length > 0) return parsed;
        } catch(e) {}
      }
    }
    return [];
  };

  const monthly_depths = getSeries(props.monthly_depths, props.observed_series, props.monthly_actual_gw);
  const monthly_dates = getSeries(props.monthly_depths_full_dates, props.monthly_depths_dates, props.monthly_dates, props.observed_dates);
  const monthly_rainfall = getSeries(props.monthly_rainfall, props.rainfall_series);
  const monthly_recharge = getSeries(props.monthly_recharge, props.recharge_series);
  const monthly_predicted = getSeries(props.monthly_predicted_gw, props.predicted_groundwater_series, props.lstm_forecast);
  const confidence = props.confidence ?? props.combined_reliability ?? props.reliability ?? 0.85;

  return {
    ...props,
    normalized_depth: currentDepth,
    normalized_risk: risk.charAt(0).toUpperCase() + risk.slice(1),
    normalized_confidence: confidence,
    normalized_monthly_depths: monthly_depths,
    normalized_monthly_dates: monthly_dates,
    normalized_monthly_rainfall: monthly_rainfall,
    normalized_monthly_recharge: monthly_recharge,
    normalized_monthly_predicted: monthly_predicted,
    is_hydrated: Boolean(props.is_hydrated || props.forecast_yearly || props.lstm_forecast || (Array.isArray(monthly_predicted) && monthly_predicted.length > 0))
  };
}
