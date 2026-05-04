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
  const sum = (coords || []).reduce((acc, c) => {
    const lon = (Array.isArray(c) && Number.isFinite(c[0])) ? c[0] : 0;
    const lat = (Array.isArray(c) && Number.isFinite(c[1])) ? c[1] : 0;
    return { lon: acc.lon + lon, lat: acc.lat + lat };
  }, {
    lon: 0,
    lat: 0
  });
  const count = (coords || []).length || 1;
  return { longitude: sum.lon / count, latitude: sum.lat / count };
}

export function healthColor(depth) {
  if (depth >= 30) return [239, 68, 68, 180]; // critical: #ef4444 (Red)
  if (depth >= 15) return [245, 158, 11, 180]; // caution: #f59e0b (Amber)
  return [34, 197, 94, 180]; // safe: #22c55e (Green)
}

export function getRiskFromDepth(depth) {
  if (depth === null || depth === undefined || !Number.isFinite(depth)) return "safe";
  if (depth >= 30) return "critical";
  if (depth >= 15) return "caution";
  return "safe";
}

export function advisoryLabel(value) {
  if (typeof value === 'number') {
    return getRiskFromDepth(value).charAt(0).toUpperCase() + getRiskFromDepth(value).slice(1);
  }
  const r = String(value || "").toLowerCase().trim();
  if (["critical", "severe", "high"].includes(r)) return "Critical";
  if (["warning", "medium", "moderate", "caution"].includes(r)) return "Caution";
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

  // 1. Depth Normalization (Priority: Actual > Predicted > Legacy > Static > Series First)
  const getFirstFiniteInSeries = (s) => {
    if (Array.isArray(s)) return s.find(v => Number.isFinite(Number(v)));
    if (typeof s === 'string' && s.startsWith('[')) {
       try {
         const p = JSON.parse(s);
         if (Array.isArray(p)) return p.find(v => Number.isFinite(Number(v)));
       } catch(e) {}
    }
    return undefined;
  };

  const depthCandidates = [
    props.current_depth,
    props.gw_level,
    props.GW_Level,
    props.depth,
    props.predicted_groundwater_level,
    props.predicted_groundwater,
    props.groundwater_level,
    props.groundwater_estimate,
    props.predicted_gw,
    props.actual_last_month,
    props.target_last_month,
    getFirstFiniteInSeries(props.monthly_depths),
    getFirstFiniteInSeries(props.monthly_predicted_gw),
    getFirstFiniteInSeries(props.predicted_groundwater_series)
  ];
  
  const currentDepthRaw = depthCandidates.find(v => v !== null && v !== undefined && String(v).trim() !== "" && !isNaN(parseFloat(v)) && isFinite(v));
  const currentDepth = (currentDepthRaw !== undefined && currentDepthRaw !== null) ? parseFloat(currentDepthRaw) : null;
  
  // 2. Risk Normalization (Critical/Caution/Safe)
  let risk = "";
  if (currentDepth !== null && Number.isFinite(currentDepth) && currentDepth > 0) {
    risk = getRiskFromDepth(currentDepth);
  } else {
    risk = String(
      props.risk_level || 
      props.normalized_risk || 
      props.Risk || 
      props.risk || 
      ""
    ).trim().toLowerCase();
  }
  
  // Final fallback if still empty
  if (!risk) risk = "safe";
  
  // Map Aliases to canonical keys: 'critical', 'caution', 'safe'
  if (["high", "severe", "critical"].includes(risk)) risk = "critical";
  if (["medium", "moderate", "caution", "warning"].includes(risk)) risk = "caution";
  if (["low", "safe"].includes(risk)) risk = "safe";
  
  if (!["critical", "caution", "safe"].includes(risk)) {
      risk = "safe";
  }

  // 4. Attribute Normalization (Richer extraction for insights)
  const toNumber = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  // Explicitly map qualitative strings if present
  let mapped_potential = null;
  const raw_potential = String(props.recharge_potential || props.potential_recharge || "").toLowerCase().trim();
  if (raw_potential === "high") mapped_potential = 0.82;
  else if (raw_potential === "medium" || raw_potential === "moderate") mapped_potential = 0.54;
  else if (raw_potential === "low") mapped_potential = 0.28;

  const recharge_score = toNumber(
    props.recharge_score ?? 
    props.recharge_index ?? 
    mapped_potential ?? 
    props.effective_recharge ?? 
    props.RECHARGE_POTENTIAL ?? 
    0.53 // Default Krishna baseline
  );
  const well_count = toNumber(props.wells_total ?? props.well_count ?? props.wells ?? props.borewell_count ?? props.WELL_COUNT);
  const monsoon_draft = toNumber(props.pumping_monsoon_draft_ha_m ?? props.monsoon_draft ?? props.monsoon_draft_ha_m ?? props.draft ?? props.Draft ?? props.MONSOON_DRAFT);
  const dist_nearest_piezo = toNumber(props.nearest_piezometer_distance_km ?? props.distance_to_nearest_piezo_km ?? props.dist_nearest_piezo ?? props.dist_nearest_piezo_km ?? props.dist_to_sensor_km ?? props.piezo_distance ?? props.DIST_NEAREST_PIEZO);
  const dist_nearest_tank = toNumber(props.distance_to_nearest_tank_km ?? props.dist_nearest_tank ?? props.dist_nearest_tank_km ?? props.tank_distance ?? props.DIST_NEAREST_TANK);

  // 5. Series Normalization (Map various names to a standard set)
  const getSeries = (...candidates) => {
    for (const c of candidates) {
      if (!c) continue;
      if (Array.isArray(c) && c.length > 0) return c;
      if (typeof c === 'string' && c.length > 2) {
        let text = c.trim();
        if (text.startsWith('[') && text.endsWith(']')) {
          try {
            // Try standard JSON first
            return JSON.parse(text);
          } catch (e) {
            try {
              // Try fixing Python-style single quotes and None
              const fixed = text.replace(/'/g, '"').replace(/None/g, 'null');
              return JSON.parse(fixed);
            } catch (e2) {
              // Last resort: manual split
              return text.slice(1, -1).split(',').map(s => {
                const val = s.trim().replace(/^["']|["']$/g, '');
                return val === 'None' ? null : val;
              });
            }
          }
        }
      }
    }
    return [];
  };

  let monthly_depths = getSeries(props.monthly_depths_full, props.monthly_depths, props.observed_series, props.monthly_actual_gw);
  let monthly_dates = getSeries(props.monthly_depths_full_dates, props.monthly_depths_dates, props.monthly_dates, props.observed_dates);

  // If we have depths but no dates, or vice versa, try the "pairs" field which is common in Python exports
  if (monthly_depths.length === 0 || monthly_dates.length === 0) {
    const pairs = getSeries(props.monthly_depths_full_pairs, props.monthly_depths_pairs);
    if (Array.isArray(pairs) && pairs.length > 0) {
      // If pairs is an array of objects like [{date: '...', depth: ...}]
      if (typeof pairs[0] === 'object' && pairs[0] !== null) {
        if (monthly_depths.length === 0) {
          monthly_depths = pairs.map(p => {
            const val = p.depth ?? p.value ?? p.gw_level;
            return (val === null || val === undefined || val === 'None') ? null : Number(val);
          });
        }
        if (monthly_dates.length === 0) {
          monthly_dates = pairs.map(p => p.date ?? p.month ?? p.time);
        }
      }
    }
  }

  const monthly_rainfall = getSeries(props.monthly_rainfall_full, props.monthly_rainfall, props.rainfall_series);
  const monthly_recharge = getSeries(props.monthly_recharge_full, props.monthly_recharge, props.recharge_series);
  const monthly_predicted = getSeries(props.monthly_predicted_gw, props.predicted_groundwater_series, props.lstm_forecast);
  const confidence = props.confidence ?? props.combined_reliability ?? props.reliability ?? 0.85;

  return {
    ...props,
    normalized_depth: currentDepth,
    normalized_risk: risk.charAt(0).toUpperCase() + risk.slice(1),
    normalized_confidence: confidence,
    normalized_recharge_score: recharge_score,
    normalized_well_count: well_count,
    normalized_monsoon_draft: monsoon_draft,
    normalized_dist_nearest_piezo: dist_nearest_piezo,
    normalized_dist_nearest_tank: dist_nearest_tank,
    normalized_monthly_depths: monthly_depths,
    normalized_monthly_dates: monthly_dates,
    normalized_monthly_rainfall: monthly_rainfall,
    normalized_monthly_recharge: monthly_recharge,
    normalized_monthly_predicted: monthly_predicted,
    is_hydrated: Boolean(props.is_hydrated || props.forecast_yearly || props.lstm_forecast || (Array.isArray(monthly_predicted) && monthly_predicted.length > 0))
  };
}

/**
 * Advanced Recharge Planning Engine - Site Selection Algorithm
 * Ranks villages based on Recharge Potential, Urgency (Stress), and Feasibility (Proximity).
 */
export function calculateAdvancedRechargePriority(featureProps) {
  const props = normalizeVillageProperties(featureProps);
  if (!props) return { score: 0, label: "Unknown", color: "transparent", priority: 0 };

  // 1. RECHARGE POTENTIAL (P) - 40% weight
  // Combines soil permeability (if available) and recharge score
  const potentialScore = props.normalized_recharge_score ?? 0.5;

  // 2. URGENCY (U) - 40% weight
  // Depletion trend (slope of depths) + Pumping stress (well density)
  let trendScore = 0.5;
  const depths = props.normalized_monthly_depths || [];
  if (depths.length >= 6) {
    const recent = depths.slice(-12).filter(v => Number.isFinite(v));
    if (recent.length >= 2) {
      const slope = (recent[recent.length - 1] - recent[0]) / recent.length;
      // positive slope means water table is falling (depth increasing)
      trendScore = clamp(0.5 + slope * 1.5, 0, 1);
    }
  }
  
  const wellDensity = clamp((props.normalized_well_count || 0) / 400, 0, 1);
  const urgencyScore = (trendScore * 0.7) + (wellDensity * 0.3);

  // 3. FEASIBILITY (F) - 20% weight
  // Proximity to surface water tanks for diversion/recharge
  const tankDist = props.normalized_dist_nearest_tank ?? 15;
  const feasibilityScore = clamp(1 / (1 + tankDist / 3), 0, 1); // 3km as half-score distance

  // WEIGHTED AGGREGATION
  const finalScore = (potentialScore * 0.4) + (urgencyScore * 0.4) + (feasibilityScore * 0.2);

  let label = "Neutral / Observation";
  let color = "transparent";
  let priority = 0;

  if (finalScore > 0.72) {
    label = "Critical Priority (Immediate AI-Recommended Site)";
    color = "#00f5d4"; // Premium Cyan
    priority = 3;
  } else if (finalScore > 0.58) {
    label = "High Priority (Diversion Intervention)";
    color = "#7dd3fc"; // Sky Blue
    priority = 2;
  } else if (finalScore > 0.42) {
    label = "Moderate Priority (Protection Zone)";
    color = "#9b5de5"; // Amethyst
    priority = 1;
  }

  return { 
    score: finalScore, 
    label, 
    color, 
    priority, 
    potential: potentialScore, 
    urgency: urgencyScore, 
    feasibility: feasibilityScore 
  };
}

export function getDistance(c1, c2) {
  if (!c1 || !c2) return Infinity;
  const lat1 = c1.latitude || c1[1];
  const lon1 = c1.longitude || c1[0];
  const lat2 = c2.latitude || c2[1];
  const lon2 = c2.longitude || c2[0];
  const dLat = lat2 - lat1;
  const dLon = lon2 - lon1;
  return Math.sqrt(dLat * dLat + dLon * dLon);
}
