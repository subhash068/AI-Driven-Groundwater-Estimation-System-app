import React, { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from "react-leaflet";
import L from "leaflet";
import { MapLegend } from './UI';
import { INITIAL_VIEW_STATE } from '../constants/data';
import { buildLocationKey, healthColor, shiftGeometryFor3D, clamp } from '../utils/mapUtils';

const isValidGeoJSON = (data) => {
  return data && (data.type === "FeatureCollection" || data.type === "Feature") && Array.isArray(data.features || [data.geometry]);
};

const LULC_COLORS = {
  water: "#38BDF8",
  trees: "#16A34A",
  flooded_vegetation: "#0EA5E9",
  crops: "#84CC16",
  built_area: "#F97316",
  bare_ground: "#D97706",
  snow_ice: "#E5E7EB",
  clouds: "#BDBDBD",
  rangeland: "#65A30D",
  unclassified: "#94A3B8"
};

const LULC_CLASSES = [
  "water",
  "trees",
  "flooded_vegetation",
  "crops",
  "built_area",
  "bare_ground",
  "snow_ice",
  "clouds",
  "rangeland"
];

function normalizeDistrictName(value) {
  return String(value || "").trim().toUpperCase();
}

function districtToSlug(value) {
  return normalizeDistrictName(value).toLowerCase().replace(/\s+/g, "_");
}

function isPointGeometry(feature) {
  return String(feature?.geometry?.type || "").toLowerCase() === "point";
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

function villageRiskColor(feature) {
  const props = feature?.properties || {};
  const depth = Number(
    props.groundwater_estimate ??
    props.predicted_groundwater_level ??
    props.estimated_groundwater_depth ??
    props.actual_last_month ??
    props.depth ??
    0
  );
  const normalized = normalizeRiskLevel(props.risk_level, depth);
  if (normalized === "critical") return "#ef4444";
  if (normalized === "warning") return "#f59e0b";
  if (normalized === "safe") return "#22c55e";
  const [r, g, b] = healthColor(depth);
  return `rgb(${r}, ${g}, ${b})`;
}

function villagePointToLayer(feature, latlng) {
  const props = feature?.properties || {};
  const color = villageRiskColor(feature);
  return L.circleMarker(latlng, {
    radius: 5.2,
    color: "#f8fafc",
    weight: 1.3,
    fillColor: color,
    fillOpacity: 0.9
  });
}

function villageInfoHtml(feature) {
  const props = feature?.properties || {};
  const gwl = Number(
    props.groundwater_estimate ??
    props.predicted_groundwater_level ??
    props.estimated_groundwater_depth ??
    props.actual_last_month ??
    props.depth ??
    NaN
  );
  const confidence = Number(props.confidence ?? props.confidence_score ?? 0);
  const risk = String(props.risk_level || "Unknown");
  const alert = String(props.alert_status || "").trim();
  const recommendation = Array.isArray(props.recommended_actions) && props.recommended_actions.length
    ? props.recommended_actions[0]
    : props.recommendation || "";
  const forecast = Array.isArray(props.forecast_3_month) ? props.forecast_3_month : [];
  const nextForecast = forecast.length ? forecast[0] : null;
  const district = String(props.district || "Unknown");
  const mandal = String(props.mandal || "Unknown");
  const village = String(props.village_name || props.village || "Unknown");
  return `
    <div style="min-width: 220px">
      <strong>Village:</strong> ${village}<br/>
      <strong>Village ID:</strong> ${props.village_id ?? "NA"}<br/>
      <strong>District:</strong> ${district}<br/>
      <strong>Mandal:</strong> ${mandal}<br/>
      <strong>Groundwater estimate:</strong> ${Number.isFinite(gwl) ? `${gwl.toFixed(2)} m` : "NA"}<br/>
      <strong>Risk level:</strong> ${risk}<br/>
      <strong>Confidence:</strong> ${Number.isFinite(confidence) ? `${confidence.toFixed(0)}%` : "NA"}<br/>
      ${alert ? `<strong>Alert:</strong> ${alert}<br/>` : ""}
      ${nextForecast ? `<strong>Next forecast:</strong> ${Number.isFinite(Number(nextForecast.predicted_groundwater_depth)) ? `${Number(nextForecast.predicted_groundwater_depth).toFixed(2)} m` : "NA"}<br/>` : ""}
      ${recommendation ? `<strong>Recommendation:</strong> ${recommendation}` : ""}
    </div>
  `;
}

function villageTooltipHtml(feature) {
  return villageInfoHtml(feature);
}

async function readGeoJsonIfValid(path) {
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const text = (await res.text()).trim();
    if (!text) return null;
    const contentType = String(res.headers.get("content-type") || "").toLowerCase();
    const looksJson = text.startsWith("{") || text.startsWith("[");
    const jsonLikeType =
      contentType.includes("application/json") ||
      contentType.includes("application/geo+json") ||
      contentType.includes("text/plain");
    if (!looksJson && !jsonLikeType) return null;
    const data = JSON.parse(text);
    return isValidGeoJSON(data) ? data : null;
  } catch {
    return null;
  }
}

function normalizeLulcCategory(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return "";
  const canonical = raw
    .replace(/[\/\s-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  const aliasMap = {
    "snow_ice": "snow_ice",
    "snow": "snow_ice",
    "ice": "snow_ice",
    "builtup": "built_area",
    "built_up": "built_area",
    "built": "built_area",
    "bare": "bare_ground",
    "bareland": "bare_ground",
    "flooded": "flooded_vegetation",
    "floodedvegetation": "flooded_vegetation"
  };
  const normalized = aliasMap[canonical] || canonical;
  return LULC_COLORS[normalized] ? normalized : "";
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function readLulcPct(props, klass, year) {
  return toNumber(props?.[`${klass}_pct_${year}`]);
}

function resolveLulcCategoryFromPercentages(props, selectedClasses = null) {
  const classes = Array.isArray(selectedClasses) && selectedClasses.length ? selectedClasses : LULC_CLASSES;
  let bestClass = "";
  let bestScore = 0;
  for (const klass of classes) {
    const pct2021 = readLulcPct(props, klass, "2021");
    const pct2011 = readLulcPct(props, klass, "2011");
    const score = pct2021 > 0 ? pct2021 : pct2011 * 0.85;
    if (score > bestScore) {
      bestScore = score;
      bestClass = klass;
    }
  }
  return bestClass && bestScore > 0 ? bestClass : "";
}

function hasSelectedLulcCoverage(props, selectedClasses) {
  if (!Array.isArray(selectedClasses) || selectedClasses.length === 0) return false;
  return selectedClasses.some((klass) => {
    const pct2021 = readLulcPct(props, klass, "2021");
    const pct2011 = readLulcPct(props, klass, "2011");
    return pct2021 > 0 || pct2011 > 0;
  });
}

function shiftRingForLulc3D(ring, depthFactor) {
  const lonShift = 0.00018 * depthFactor;
  const latShift = -0.00013 * depthFactor;
  return ring.map(([lon, lat]) => [lon + lonShift, lat + latShift]);
}

function shiftGeometryForLulc3D(geometry, depthFactor) {
  if (!geometry) return null;
  if (geometry.type === "Polygon") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((ring) => shiftRingForLulc3D(ring, depthFactor))
    };
  }
  if (geometry.type === "MultiPolygon") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((poly) =>
        poly.map((ring) => shiftRingForLulc3D(ring, depthFactor))
      )
    };
  }
  return geometry;
}

function FlyToSelection({ popupLngLat, selectedFeature, filters }) {
  const map = useMap();
  useEffect(() => {
    // When a broader filter is active (state/district/mandal), filter-fit should own zoom behavior.
    if ((filters?.state || filters?.district || filters?.mandal) && !filters?.villageName) return;
    if (!selectedFeature) return;
    const bounds = L.geoJSON(selectedFeature).getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.35), { duration: 0.9 });
      return;
    }
    if (popupLngLat) {
      map.flyTo([popupLngLat[1], popupLngLat[0]], 10.5, { duration: 0.9 });
    }
  }, [map, popupLngLat, selectedFeature, filters?.state, filters?.district, filters?.mandal, filters?.villageName]);
  return null;
}

function FitToFilterSelection({ filteredGeojson, filters }) {
  const map = useMap();
  const lastZoomKeyRef = useRef("");

  useEffect(() => {
    const hasLocationFilter =
      Boolean(filters?.state) ||
      Boolean(filters?.district) ||
      Boolean(filters?.mandal) ||
      Boolean(filters?.villageName);

    if (!hasLocationFilter) {
      const noFilterKey = "INDIA_DEFAULT";
      if (lastZoomKeyRef.current === noFilterKey) return;
      lastZoomKeyRef.current = noFilterKey;
      map.flyTo([20.5937, 78.9629], 5, { duration: 0.9 });
      return;
    }

    if (!filteredGeojson?.features?.length) return;

    const zoomKey = [
      filters?.state || "",
      filters?.district || "",
      filters?.mandal || "",
      filters?.villageName || "",
      filteredGeojson.features.length
    ].join("|");

    if (lastZoomKeyRef.current === zoomKey) return;
    lastZoomKeyRef.current = zoomKey;

    let dataToFit = filteredGeojson;
    let padding = 0.12;
    let maxZoom = 8.8;

    const districtOnly = Boolean(filters?.district) && !filters?.mandal && !filters?.villageName;

    if (filters?.district) {
      padding = 0.14;
      maxZoom = 11;
    }

    if (filters?.mandal) {
      padding = 0.18;
      maxZoom = 12;
    }

    if (filters?.villageName) {
      dataToFit = filteredGeojson.features[0];
      padding = 0.25;
      maxZoom = 14;
    }

    const bounds = L.geoJSON(dataToFit).getBounds();
    if (!bounds.isValid()) return;

    if (districtOnly) {
      const center = bounds.getCenter();
      map.flyTo([center.lat, center.lng], 10.4, { duration: 0.9 });
      map.fitBounds(bounds.pad(0.16), { duration: 0.9, maxZoom: 11.2 });
      return;
    }

    map.fitBounds(bounds.pad(padding), { duration: 0.9, maxZoom });
  }, [
    map,
    filteredGeojson,
    filters?.state,
    filters?.district,
    filters?.mandal,
    filters?.villageName
  ]);

  return null;
}

export function MapView({ 
  filteredGeojson, 
  monthIndex, 
  is3D, 
  onVillageClick, 
  onDistrictHover, 
  selectedFeature, 
  popupLngLat, 
  filters,
  showLulc,
  showGroundwaterLevels,
  showPiezometers,
  showWells,
  selectedAnomalyTypes,
  showDistrictBoundaries,
  showMandalBoundaries,
  selectedLulcClasses,
  showRecharge,
  villageDataError,
  villageDataSource,
  datasetRowsById,
  datasetRowsByLocation,
  anomalies,
  rechargeZones,
  selectedDistrict
}) {
  const [hoverBadge, setHoverBadge] = useState(null);
  const [hoveredDistrictName, setHoveredDistrictName] = useState(null);
  const [aquiferGeojson, setAquiferGeojson] = useState(null);
  const [piezometerStations, setPiezometerStations] = useState([]);
  const [wellPoints, setWellPoints] = useState([]);
  const hoverFrameRef = useRef(null);
  const pendingHoverRef = useRef(null);
  const activeDistrictRef = useRef(null);
  const selectedDistrictNorm = normalizeDistrictName(selectedDistrict);

  const boundaryColorFromText = (text) => {
    const value = String(text || "boundary");
    let hash = 0;
    for (let i = 0; i < value.length; i += 1) {
      hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
    }
    const hue = hash % 360;
    return `hsl(${hue} 72% 58%)`;
  };

  const piezometerColor = (value, min, max) => {
    if (!Number.isFinite(value)) return "#94A3B8";
    const span = Math.max(max - min, 1);
    const ratio = Math.max(0, Math.min(1, (value - min) / span));
    const red = Math.round(220 - 130 * ratio);
    const green = Math.round(56 + 70 * ratio);
    const blue = Math.round(48 + 176 * ratio);
    return `rgb(${red}, ${green}, ${blue})`;
  };

  const wellTypeColor = (type) => {
    const value = String(type || "").toLowerCase();
    if (value.includes("tube")) return "#F59E0B";
    if (value.includes("open")) return "#22C55E";
    if (value.includes("filter")) return "#14B8A6";
    if (value.includes("dug")) return "#8B5CF6";
    if (value.includes("bore")) return "#38BDF8";
    return "#94A3B8";
  };

  const aquiferTypeMeta = (feature) => {
    const props = feature?.properties || {};
    const klass = String(props.Geo_Class || props.aquifer_type || "Aquifer unit").trim();
    const lower = klass.toLowerCase();
    if (lower.includes("alluv")) {
      return { label: "Alluvium", color: "#7DD3FC" };
    }
    if (
      lower.includes("shale") ||
      lower.includes("sand stone") ||
      lower.includes("sandstone") ||
      lower.includes("lime stone") ||
      lower.includes("limestone")
    ) {
      return { label: "Fractured Rock", color: "#FB923C" };
    }
    return { label: "Hard Rock", color: "#8B5E34" };
  };

  const anomalyMeta = (feature) => {
    const props = feature?.properties || {};
    const rawType = String(props.anomaly_type || props.type || props.reason || "Normal").toLowerCase();
    const score = Number(props.anomaly_score);
    const normalizedScore = Number.isFinite(score) ? Math.abs(score) : 0;

    if (rawType.includes("rise") || rawType.includes("increase") || rawType.includes("up")) {
      return {
        label: "Rise",
        color: "#3B82F6",
        radius: clamp(5.5 + normalizedScore * 2.5, 5.5, 9.5)
      };
    }
    if (rawType.includes("severe") || rawType.includes("extreme") || normalizedScore >= 0.75) {
      return {
        label: "Severe drop",
        color: "#EF4444",
        radius: clamp(6.5 + normalizedScore * 4, 6.5, 10.5)
      };
    }
    if (
      rawType.includes("moderate") ||
      rawType.includes("drop") ||
      rawType.includes("decline") ||
      rawType.includes("fall") ||
      normalizedScore >= 0.35
    ) {
      return {
        label: "Moderate drop",
        color: "#F59E0B",
        radius: clamp(5.8 + normalizedScore * 3, 5.8, 9)
      };
    }
    if (rawType.includes("normal")) {
      return {
        label: "Normal",
        color: "#FACC15",
        radius: clamp(5.2 + normalizedScore * 1.5, 5.2, 7.5)
      };
    }
    return {
      label: "Normal",
      color: "#FACC15",
      radius: clamp(5.2 + normalizedScore * 1.5, 5.2, 7.5)
    };
  };

  const anomalyTooltipHtml = (feature) => {
    const props = feature?.properties || {};
    const villageId = Number(props.village_id);
    const locationKey = buildLocationKey(props.district, props.mandal, props.village_name);
    const row =
      (locationKey && datasetRowsByLocation?.get(locationKey)) ||
      (Number.isFinite(villageId) ? datasetRowsById?.get(villageId) : null);
    const villageName = row?.village_name || props.village_name || `Village ${props.village_id || "NA"}`;
    const rawType = String(props.anomaly_type || props.type || props.reason || "Normal");
    const anomalyClass = anomalyMeta(feature).label;
    const deviation = Number(props.deviation_m ?? props.anomaly_score);
    const currentGroundwater = Number(row?.gw_level ?? row?.actual_last_month ?? row?.predicted_groundwater_level);
    const district = row?.district || props.district || selectedDistrict || "Unknown";
    const mandal = row?.mandal || props.mandal || "Unknown";
    return `
      <div style="min-width: 190px">
        <strong>Village:</strong> ${villageName}<br/>
        <strong>District:</strong> ${district}<br/>
        <strong>Mandal:</strong> ${mandal}<br/>
        <strong>Groundwater deviation:</strong> ${Number.isFinite(deviation) ? `${deviation.toFixed(2)} m` : "NA"}<br/>
        <strong>Type of anomaly:</strong> ${anomalyClass}<br/>
        <strong>Raw label:</strong> ${rawType}<br/>
        <strong>Groundwater level:</strong> ${Number.isFinite(currentGroundwater) ? `${currentGroundwater.toFixed(2)} m` : "NA"}
      </div>
    `;
  };

  useEffect(() => {
    let active = true;
    (async () => {
      const districtSlug = districtToSlug(selectedDistrict);
      const preferredPaths = districtSlug === "krishna"
        ? ["/data/aquifers_krishna.geojson"]
        : [];
      let data = null;
      for (const path of preferredPaths) {
        data = await readGeoJsonIfValid(path);
        if (data) break;
      }
      if (active && data) {
        setAquiferGeojson(data);
      } else if (active) {
        setAquiferGeojson(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedDistrict]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const districtSlug = districtToSlug(selectedDistrict);
        const candidatePaths = districtSlug === "krishna"
          ? ["/data/krishna_piezometers.json"]
          : districtSlug === "ntr"
            ? ["/data/ntr_piezometers.json"]
            : [];

        let stations = [];
        for (const path of candidatePaths) {
          const response = await fetch(path, { headers: { Accept: "application/json" } });
          if (!response.ok) continue;
          const payload = await response.json();
          const candidateStations = Array.isArray(payload?.stations) ? payload.stations : [];
          if (candidateStations.length > 0) {
            stations = candidateStations;
            break;
          }
        }
        if (!active) return;
        setPiezometerStations(
          stations.filter((station) =>
            Number.isFinite(Number(station?.latitude)) &&
            Number.isFinite(Number(station?.longitude)) &&
            (!selectedDistrictNorm || normalizeDistrictName(station?.district) === selectedDistrictNorm)
          )
        );
      } catch {
        if (active) setPiezometerStations([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedDistrict, selectedDistrictNorm]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const districtSlug = districtToSlug(selectedDistrict);
        const candidatePaths = districtSlug === "krishna"
          ? ["/data/wells_krishna.json"]
          : [];

        let features = [];
        for (const path of candidatePaths) {
          const response = await fetch(path, { headers: { Accept: "application/json" } });
          if (!response.ok) continue;
          const payload = await response.json();
          const candidateFeatures = Array.isArray(payload?.features) ? payload.features : [];
          if (candidateFeatures.length > 0) {
            features = candidateFeatures;
            break;
          }
        }
        if (!active) return;
        setWellPoints(
          features.filter((feature) =>
            Number.isFinite(Number(feature?.geometry?.coordinates?.[0])) &&
            Number.isFinite(Number(feature?.geometry?.coordinates?.[1])) &&
            (!selectedDistrictNorm || normalizeDistrictName(feature?.properties?.district) === selectedDistrictNorm)
          )
        );
      } catch {
        if (active) setWellPoints([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedDistrict, selectedDistrictNorm]);

  const extrusionGeojson = useMemo(() => {
    if (!filteredGeojson || !is3D) return null;
    const features = filteredGeojson.features
      .map((f) => {
        const weathered = Number(f.properties?.weathered_rock || 0);
        const fractured = Number(f.properties?.fractured_rock || 0);
        const pseudoHeight = clamp((weathered + fractured) / 8, 0.8, 4.6);
        return {
          ...f,
          geometry: shiftGeometryFor3D(f.geometry, pseudoHeight)
        };
      })
      .filter((f) => f.geometry);
    return { type: "FeatureCollection", features };
  }, [filteredGeojson, is3D]);

  const groundwaterStyle = (feature) => {
    const props = feature?.properties || {};
    const depth = Number(
      props.groundwater_estimate ??
      props.predicted_groundwater_level ??
      props.estimated_groundwater_depth ??
      props.monthly_depths?.[monthIndex] ??
      props.actual_last_month ??
      props.depth ??
      0
    );
    const color = villageRiskColor(feature);
    return {
      color: "rgba(15, 23, 42, 0.55)",
      weight: 1.2,
      fillColor: color,
      fillOpacity: Number.isFinite(depth) ? 0.76 : 0.4
    };
  };

  const neutralVillageStyle = () => ({
    color: "rgba(50, 50, 50, 0.35)",
    weight: 1,
    fillColor: "#2b3440",
    fillOpacity: 0.15
  });

  const selectedVillageStyle = (feature) => {
    const depth = Number(
      feature?.properties?.groundwater_estimate ??
      feature?.properties?.predicted_groundwater_level ??
      feature?.properties?.estimated_groundwater_depth ??
      feature?.properties?.monthly_depths?.[monthIndex] ??
      feature?.properties?.actual_last_month ??
      feature?.properties?.depth ??
      0
    );
    const color = villageRiskColor(feature);
    return {
      color: "#000000",
      weight: 2.8,
      opacity: 1,
      fillColor: color,
      fillOpacity: Number.isFinite(depth) ? 0.86 : 0.18
    };
  };

  const isSelectedVillageFeature = (feature) => {
    if (!feature || !selectedFeature) return false;
    const featureVillageId = Number(feature?.properties?.village_id);
    const selectedVillageId = Number(selectedFeature?.properties?.village_id);
    if (Number.isFinite(featureVillageId) && Number.isFinite(selectedVillageId)) {
      return featureVillageId === selectedVillageId;
    }
    const featureKey = buildLocationKey(
      feature?.properties?.district,
      feature?.properties?.mandal,
      feature?.properties?.village_name
    );
    const selectedKey = buildLocationKey(
      selectedFeature?.properties?.district,
      selectedFeature?.properties?.mandal,
      selectedFeature?.properties?.village_name
    );
    return featureKey === selectedKey;
  };

  const extrusionStyle = (feature) => {
    const monthly = feature?.properties?.monthly_depths || [];
    const depth = Number(monthly[monthIndex] ?? feature?.properties?.depth ?? 0);
    const [r, g, b] = healthColor(depth);
    return {
      color: `rgba(${Math.max(0, r - 40)}, ${Math.max(0, g - 40)}, ${Math.max(0, b - 40)}, 0.65)`,
      weight: 0.6,
      fillColor: `rgb(${Math.max(0, r - 55)}, ${Math.max(0, g - 55)}, ${Math.max(0, b - 55)})`,
      fillOpacity: 0.5
    };
  };

  const villageEvents = useMemo(() => ({
    mouseover: (event) => {
      const props = event?.layer?.feature?.properties || {};
      const district = props.district;
      const mandal = props.mandal;
      const village = props.village_name;
      const point = event?.containerPoint;
      const nextDistrict = district || null;
      if (activeDistrictRef.current !== nextDistrict) {
        activeDistrictRef.current = nextDistrict;
        setHoveredDistrictName(nextDistrict);
        onDistrictHover(nextDistrict);
      }
      if (point) {
        setHoverBadge({
          district: district || "Unknown",
          mandal: mandal || "Unknown",
          village: village || "Unknown",
          x: point.x,
          y: point.y
        });
      }
    },
    mousemove: (event) => {
      const props = event?.layer?.feature?.properties || {};
      const district = props.district;
      const mandal = props.mandal;
      const village = props.village_name;
      const point = event?.containerPoint;
      if (point) {
        pendingHoverRef.current = {
          district: district || "Unknown",
          mandal: mandal || "Unknown",
          village: village || "Unknown",
          x: point.x,
          y: point.y
        };
        if (hoverFrameRef.current !== null) return;
        hoverFrameRef.current = window.requestAnimationFrame(() => {
          hoverFrameRef.current = null;
          if (pendingHoverRef.current) {
            setHoverBadge(pendingHoverRef.current);
          }
        });
      }
    },
    mouseout: () => {
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current);
        hoverFrameRef.current = null;
      }
      pendingHoverRef.current = null;
      activeDistrictRef.current = null;
      setHoveredDistrictName(null);
      setHoverBadge(null);
      onDistrictHover(null);
    },
    click: (event) => {
      event?.originalEvent?.stopPropagation?.();
      const feature = event?.layer?.feature;
      if (!feature) return;
      onVillageClick(feature);
    }
  }), [onDistrictHover, onVillageClick]);

  useEffect(() => {
    return () => {
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current);
      }
    };
  }, []);

  const visibleAnomalies = useMemo(() => {
    if (!anomalies || !isValidGeoJSON(anomalies)) return null;
    const selected = Array.isArray(selectedAnomalyTypes) ? selectedAnomalyTypes : [];
    const allowedVillageIds = new Set(
      (filteredGeojson?.features || [])
        .map((feature) => Number(feature?.properties?.village_id))
        .filter((value) => Number.isFinite(value))
    );
    if (selected.length === 0) {
      return { type: "FeatureCollection", features: [] };
    }
    return {
      ...anomalies,
      features: anomalies.features.filter((feature) => {
        const villageId = Number(feature?.properties?.village_id);
        const district = normalizeDistrictName(feature?.properties?.district);
        const districtMatch = !selectedDistrictNorm || district === selectedDistrictNorm;
        const villageMatch = !allowedVillageIds.size || allowedVillageIds.has(villageId);
        return selected.includes(anomalyMeta(feature).label) && districtMatch && villageMatch;
      })
    };
  }, [anomalies, selectedAnomalyTypes, selectedDistrictNorm, filteredGeojson]);

  const severeAnomalyHighlightGeojson = useMemo(() => {
    if (!filteredGeojson?.features?.length || !visibleAnomalies?.features?.length) return null;
    const severeSelected = Array.isArray(selectedAnomalyTypes) && selectedAnomalyTypes.includes("Severe drop");
    if (!severeSelected) return null;
    const severeVillageIds = new Set(
      visibleAnomalies.features
        .filter((feature) => anomalyMeta(feature).label === "Severe drop")
        .map((feature) => Number(feature?.properties?.village_id))
        .filter((value) => Number.isFinite(value))
    );
    if (!severeVillageIds.size) return null;
    const features = filteredGeojson.features.filter((feature) => severeVillageIds.has(Number(feature?.properties?.village_id)));
    if (!features.length) return null;
    return { type: "FeatureCollection", features };
  }, [filteredGeojson, selectedAnomalyTypes, visibleAnomalies]);

  const anomalyEmptyState = Boolean(anomalies && isValidGeoJSON(anomalies) && Array.isArray(selectedAnomalyTypes) && selectedAnomalyTypes.length === 0);

  const lulcGeojson = useMemo(() => {
    if (!showLulc || !filteredGeojson?.features?.length) return null;
    const selected = (selectedLulcClasses || []).map((item) => String(item));
    const selectedSet = new Set(selected);
    if (selectedSet.size === 0) {
      return { ...filteredGeojson, features: [] };
    }
    return {
      ...filteredGeojson,
      features: filteredGeojson.features
        .map((feature) => {
          const props = feature?.properties || {};
          const byPct = resolveLulcCategoryFromPercentages(props, selected);
          const fallback =
            normalizeLulcCategory(props.lulc_2021_dominant || props.lulc || props.land_use) ||
            normalizeLulcCategory(props.lulc_2011_dominant) ||
            "unclassified";
          const category = byPct || (selectedSet.has(fallback) ? fallback : "");
          const selectedCoverage = hasSelectedLulcCoverage(props, selected);
          return {
            ...feature,
            properties: {
              ...props,
              __lulcCategory: category || fallback,
              __lulcSelectedCoverage: selectedCoverage
            }
          };
        })
        .filter((feature) => Boolean(feature?.properties?.__lulcSelectedCoverage))
    };
  }, [filteredGeojson, showLulc, selectedLulcClasses]);

  const lulc3DGeojson = useMemo(() => {
    if (!is3D || !lulcGeojson?.features?.length) return null;
    const features = lulcGeojson.features
      .map((feature) => {
        const category = feature?.properties?.__lulcCategory || "unclassified";
        const offsetByClass = {
          water: 1.1,
          trees: 1.7,
          flooded_vegetation: 1.35,
          crops: 1.45,
          built_area: 2.0,
          bare_ground: 1.2,
          snow_ice: 1.15,
          clouds: 1.25,
          rangeland: 1.4
        };
        const depthWeight = Number(feature?.properties?.depth ?? 16);
        const pseudoHeight = clamp((depthWeight / 18) * (offsetByClass[category] || 1.2), 0.9, 4.8);
        return {
          ...feature,
          geometry: shiftGeometryForLulc3D(feature.geometry, pseudoHeight),
          properties: {
            ...(feature.properties || {}),
            __lulcPseudoHeight: pseudoHeight
          }
        };
      })
      .filter((feature) => feature.geometry);
    return { type: "FeatureCollection", features };
  }, [is3D, lulcGeojson]);

  const piezometerGeojson = useMemo(() => {
    if (!showPiezometers || !piezometerStations.length) return null;
    const values = piezometerStations
      .map((station) => Number(station?.latestReading2024?.value))
      .filter((value) => Number.isFinite(value));
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 1;
    return {
      type: "FeatureCollection",
      features: piezometerStations.map((station) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [Number(station.longitude), Number(station.latitude)]
        },
        properties: {
          ...station,
          _latestValue: Number(station?.latestReading2024?.value),
          _minValue: min,
          _maxValue: max
        }
      }))
    };
  }, [showPiezometers, piezometerStations]);

  const piezometerTooltipHtml = (feature) => {
    const props = feature?.properties || {};
    const latestReading = props.latestReading2024 || {};
    const observationCount = Array.isArray(props.monthlyReadings2024) ? props.monthlyReadings2024.length : null;
    const latestValue = Number(props._latestValue);
    const totalDepth = Number(props.totalDepthM);
    const latestLabel = latestReading.label || "2024";
    return `
      <div style="min-width: 180px">
        <strong>Station:</strong> ${props.id || "NA"}<br/>
        <strong>Village:</strong> ${props.village || "NA"}<br/>
        <strong>Latest GWL:</strong> ${Number.isFinite(latestValue) ? `${latestValue.toFixed(2)} m` : "NA"}<br/>
        <strong>Observation depth:</strong> ${Number.isFinite(totalDepth) ? `${totalDepth.toFixed(2)} m` : "NA"}<br/>
        <strong>Observations:</strong> ${observationCount ?? "NA"}<br/>
        <strong>Latest reading:</strong> ${latestLabel}
      </div>
    `;
  };

  const wellTooltipHtml = (feature) => {
    const props = feature?.properties || {};
    const wellCount = Number(props.well_count);
    const workingPct = Number(props.working_pct);
    const boreDepth = Number(props.avg_bore_depth_m);
    const pumpCapacity = Number(props.avg_pump_capacity_hp);
    return `
      <div style="min-width: 190px">
        <strong>Village:</strong> ${props.village || "NA"}<br/>
        <strong>Well type:</strong> ${props.dominant_well_type || "NA"}<br/>
        <strong>Bore depth:</strong> ${Number.isFinite(boreDepth) ? `${boreDepth.toFixed(2)} m` : "NA"}<br/>
        <strong>Pump capacity:</strong> ${Number.isFinite(pumpCapacity) ? `${pumpCapacity.toFixed(2)} HP` : "NA"}<br/>
        <strong>Irrigation type:</strong> ${props.dominant_irrigation || "NA"}<br/>
        <strong>Wells:</strong> ${Number.isFinite(wellCount) ? wellCount : "NA"}<br/>
        <strong>Working:</strong> ${Number.isFinite(workingPct) ? `${workingPct.toFixed(2)}%` : "NA"}
      </div>
    `;
  };

  const wellsGeojson = useMemo(() => {
    if (!showWells || !wellPoints.length) return null;
    return {
      type: "FeatureCollection",
      features: wellPoints
    };
  }, [showWells, wellPoints]);

  const districtNote = useMemo(() => {
    if (selectedDistrictNorm === "NTR") {
      return "NTR: Point-based representation";
    }
    return null;
  }, [selectedDistrictNorm]);

const baseTileUrl = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

  const baseTileAttribution =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  return (
    <>
      {!filteredGeojson?.features?.length && (
        <div
          style={{
            position: "absolute",
            zIndex: 600,
            right: "18px",
            top: "18px",
            maxWidth: "360px",
            background: "rgba(8, 15, 24, 0.92)",
            border: "1px solid rgba(56, 189, 248, 0.45)",
            color: "#dbeafe",
            borderRadius: "10px",
            padding: "12px 14px",
            fontSize: "0.82rem",
            lineHeight: 1.45,
            backdropFilter: "blur(2px)"
          }}
        >
          <strong style={{ display: "block", marginBottom: "4px", color: "#7dd3fc" }}>
            {villageDataSource ? "No Villages Match Current Filters" : "Village Boundaries Missing"}
          </strong>
          <div>
            {villageDataSource
              ? "Boundary file is loaded, but current filter selection returned zero villages."
              : villageDataError || "No real village polygons are loaded."}
          </div>
          {!villageDataSource && (
            <div style={{ marginTop: "6px", color: "#93c5fd" }}>
              Add your file at <code>/frontend/public/data/village_boundaries.geojson</code>.
            </div>
          )}
          {villageDataSource && (
            <div style={{ marginTop: "4px", color: "#67e8f9" }}>
              Active source: <code>{villageDataSource}</code>
            </div>
          )}
        </div>
      )}
      <MapContainer
        center={[INITIAL_VIEW_STATE.latitude, INITIAL_VIEW_STATE.longitude]}
        zoom={INITIAL_VIEW_STATE.zoom}
        className="leaflet-map"
        preferCanvas
      >
        <TileLayer attribution={baseTileAttribution} url={baseTileUrl} />

        {extrusionGeojson && <GeoJSON data={extrusionGeojson} style={extrusionStyle} interactive={false} />}
        {filteredGeojson && (
          <GeoJSON
            data={filteredGeojson}
            style={(feature) => {
              if (isSelectedVillageFeature(feature)) {
                return selectedVillageStyle(feature);
              }
              return showGroundwaterLevels ? groundwaterStyle(feature) : neutralVillageStyle(feature);
            }}
            eventHandlers={villageEvents}
            pointToLayer={(feature, latlng) => (isPointGeometry(feature) ? villagePointToLayer(feature, latlng) : undefined)}
            onEachFeature={(feature, layer) => {
              const popupHtml = villageInfoHtml(feature);
              if (layer?.bindTooltip) {
                layer.bindTooltip(popupHtml, {
                  sticky: true,
                  direction: "top",
                  opacity: 0.96,
                  className: "village-tooltip"
                });
              }
              if (layer?.bindPopup) {
                layer.bindPopup(popupHtml, {
                  className: "village-popup",
                  closeButton: true,
                  autoPan: true,
                  maxWidth: 320
                });
              }
            }}
          />
        )}
        {showDistrictBoundaries && filteredGeojson && (
          <GeoJSON
            data={filteredGeojson}
            style={(feature) => {
              const district = String(feature?.properties?.district || "District");
              const color = boundaryColorFromText(district);
              return {
                color,
                weight: 1.9,
                fillColor: color,
                fillOpacity: 0.01,
                dashArray: "4, 4"
              };
            }}
            pointToLayer={(feature, latlng) => (isPointGeometry(feature) ? villagePointToLayer(feature, latlng) : undefined)}
            interactive={false}
          />
        )}
        {showMandalBoundaries && filteredGeojson && (
          <GeoJSON
            data={filteredGeojson}
            style={(feature) => {
              const mandal = String(feature?.properties?.mandal || "Mandal");
              const color = boundaryColorFromText(mandal);
              return {
                color,
                weight: 1.2,
                fillColor: color,
                fillOpacity: 0.005,
                dashArray: "2, 6"
              };
            }}
            pointToLayer={(feature, latlng) => (isPointGeometry(feature) ? villagePointToLayer(feature, latlng) : undefined)}
            interactive={false}
          />
        )}
        {lulc3DGeojson && (
          <GeoJSON
            data={lulc3DGeojson}
            style={(feature) => {
              const category = feature?.properties?.__lulcCategory || "unclassified";
              const color = LULC_COLORS[category] || LULC_COLORS.unclassified;
              return {
                color: "#0b1320",
                weight: 1.2,
                fillColor: color,
                fillOpacity: 0.72
              };
            }}
            interactive={false}
          />
        )}

        {lulcGeojson && (
          <GeoJSON
            data={lulcGeojson}
            style={(feature) => {
              const category = feature?.properties?.__lulcCategory || "unclassified";
              const color = LULC_COLORS[category] || LULC_COLORS.unclassified;
              return {
                color,
                weight: is3D ? 0.9 : 1.2,
                fillColor: color,
                fillOpacity: is3D ? 0.12 : 0.22
              };
            }}
            onEachFeature={(feature, layer) => {
              const category = feature?.properties?.__lulcCategory || "unclassified";
              const labelMap = {
                water: "Water",
                trees: "Trees",
                flooded_vegetation: "Flooded Vegetation",
                crops: "Crops",
                built_area: "Built Area",
                bare_ground: "Bare Ground",
                snow_ice: "Snow/Ice",
                clouds: "Clouds",
                rangeland: "Rangeland",
                unclassified: "Unclassified"
              };
              const p = feature?.properties || {};
              const d11 = labelMap[String(p.lulc_2011_dominant || "").toLowerCase()] || "NA";
              const d21 = labelMap[String(p.lulc_2021_dominant || "").toLowerCase()] || "NA";
              const delta = String(p.lulc_change || "NA");
              layer.bindTooltip(`LULC 2021: ${labelMap[category] || "Unclassified"}\n2011: ${d11} | 2021: ${d21}\nChange: ${delta}`);
            }}
          />
        )}

        {rechargeZones && isValidGeoJSON(rechargeZones) && (
          <GeoJSON 
            data={rechargeZones} 
            style={{ color: '#00e5ff', weight: 2, dashArray: '5, 5', fillOpacity: 0.1 }} 
          />
        )}

        {visibleAnomalies && visibleAnomalies.features.length > 0 && (
          <GeoJSON 
            data={visibleAnomalies} 
            pointToLayer={(feature, latlng) => L.circleMarker(latlng, {
              radius: anomalyMeta(feature).radius,
              fillColor: anomalyMeta(feature).color,
              color: "#f8fafc",
              weight: 1.3,
              opacity: 1,
              fillOpacity: 0.88
            })}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(anomalyTooltipHtml(feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "anomaly-tooltip"
              });
              layer.on?.("click", () => {
                const villageId = Number(feature?.properties?.village_id);
                const anomalyDistrict = normalizeDistrictName(feature?.properties?.district || "");
                const anomalyMandal = String(feature?.properties?.mandal || "").trim();
                const anomalyVillage = String(feature?.properties?.village_name || "").trim();
                const anomalyKey = buildLocationKey(anomalyDistrict, anomalyMandal, anomalyVillage);
                let matched = null;
                if (anomalyKey) {
                  matched = (filteredGeojson?.features || []).find((item) => {
                    const itemKey = buildLocationKey(
                      item?.properties?.district,
                      item?.properties?.mandal,
                      item?.properties?.village_name
                    );
                    return itemKey === anomalyKey;
                  });
                }
                if (!matched && Number.isFinite(villageId)) {
                  matched = (filteredGeojson?.features || []).find((item) => Number(item?.properties?.village_id) === villageId);
                }
                if (matched) {
                  onVillageClick(matched);
                }
              });
            }}
            />
        )}

        {anomalyEmptyState && (
          <div
            style={{
              position: "absolute",
              zIndex: 610,
              right: "18px",
              top: "18px",
              maxWidth: "320px",
              background: "rgba(8, 15, 24, 0.92)",
              border: "1px solid rgba(59, 130, 246, 0.45)",
              color: "#dbeafe",
              borderRadius: "10px",
              padding: "12px 14px",
              fontSize: "0.82rem",
              lineHeight: 1.45
            }}
          >
            <strong style={{ display: "block", marginBottom: "4px", color: "#93c5fd" }}>
              No anomaly types selected
            </strong>
            <div>Choose one or more anomaly severities in the sidebar to display markers.</div>
          </div>
        )}

        {piezometerGeojson && (
          <GeoJSON
            data={piezometerGeojson}
            pointToLayer={(feature, latlng) => {
              const props = feature?.properties || {};
              const min = Number(props._minValue);
              const max = Number(props._maxValue);
              const value = Number(props._latestValue);
              const color = piezometerColor(value, min, max);
              const count = Array.isArray(props.monthlyReadings2024) ? props.monthlyReadings2024.length : 1;
              const radius = clamp(5 + Math.min(count, 12) * 0.18, 5.2, 7.4);
              return L.circleMarker(latlng, {
                radius,
                color: "#f8fafc",
                weight: 1.5,
                fillColor: color,
                fillOpacity: 0.92
              });
            }}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(piezometerTooltipHtml(feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "piezometer-tooltip"
              });
            }}
          />
        )}

        {wellsGeojson && (
          <GeoJSON
            data={wellsGeojson}
            pointToLayer={(feature, latlng) => {
              const props = feature?.properties || {};
              const wellCount = Number(props.well_count);
              const radius = clamp(3.5 + Math.min(Number.isFinite(wellCount) ? wellCount : 0, 900) / 320, 3.5, 6.2);
              return L.circleMarker(latlng, {
                radius,
                color: "#f8fafc",
                weight: 1.1,
                fillColor: wellTypeColor(props.dominant_well_type),
                fillOpacity: 0.82
              });
            }}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(wellTooltipHtml(feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "wells-tooltip"
              });
            }}
          />
        )}

        {showRecharge && aquiferGeojson && (
          <GeoJSON
            data={aquiferGeojson}
            style={(feature) => {
              const meta = aquiferTypeMeta(feature);
              return {
                color: meta.color,
                weight: 1.4,
                dashArray: "6, 4",
                fillColor: meta.color,
                fillOpacity: 0.24
              };
            }}
            onEachFeature={(feature, layer) => {
              const props = feature?.properties || {};
              const code = props.AQUI_CODE || "NA";
              const klass = aquiferTypeMeta(feature).label || props.Geo_Class || "Aquifer unit";
              const area = props.area ?? "NA";
              layer.bindTooltip(`
                <div style="min-width: 160px">
                  <strong>Aquifer type:</strong> ${klass}<br/>
                  <strong>Aquifer code:</strong> ${code}<br/>
                  <strong>Depth / thickness:</strong> NA<br/>
                  <strong>Area:</strong> ${area} km2
                </div>
              `, {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "aquifer-tooltip"
              });
            }}
          />
        )}

        {severeAnomalyHighlightGeojson && (
          <GeoJSON
            data={severeAnomalyHighlightGeojson}
            style={{
              color: "#F97316",
              weight: 2.8,
              fillOpacity: 0.02,
              dashArray: "3, 5"
            }}
            interactive={false}
          />
        )}

        <FlyToSelection popupLngLat={popupLngLat} selectedFeature={selectedFeature} filters={filters} />
        <FitToFilterSelection filteredGeojson={filteredGeojson} filters={filters} />
      <MapLegend
        showGroundwaterLevels={showGroundwaterLevels}
        showPiezometers={showPiezometers}
        showWells={showWells}
        showAnomalies={Boolean(anomalies && isValidGeoJSON(anomalies))}
        districtNote={districtNote}
      />
      </MapContainer>

      {hoverBadge && (
        <div
          className="district-hover-badge"
          style={{
            left: `${hoverBadge.x + 18}px`,
            top: `${hoverBadge.y + 18}px`
          }}
        >
          <div><strong>District:</strong> {hoverBadge.district}</div>
          <div><strong>Mandal:</strong> {hoverBadge.mandal}</div>
          <div><strong>Village:</strong> {hoverBadge.village}</div>
        </div>
      )}
    </>
  );
}
