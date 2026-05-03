import React, { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, ImageOverlay, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { MapLegend } from './UI';
import { INITIAL_VIEW_STATE } from '../constants/data';
import { buildLocationKey, healthColor, shiftGeometryFor3D, clamp, getRiskFromDepth, normalizeVillageProperties, calculateAdvancedRechargePriority } from '../utils/mapUtils';
import WellsLayerController from './WellsLayer';

const isValidGeoJSON = (data) => {
  return data && (data.type === "FeatureCollection" || data.type === "Feature") && Array.isArray(data.features || [data.geometry]);
};

const LULC_COLORS = {
  water: "#2B5797",
  trees: "#3E7B27",
  flooded_vegetation: "#91D18B",
  crops: "#F7DC6F",
  built_area: "#D94436",
  bare_ground: "#EAECEE",
  snow_ice: "#FDFEFE",
  clouds: "#BDC3C7",
  rangeland: "#F5CBA7",
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


function cleanText(val, fallback = "NA") {
  if (val === null || val === undefined) return fallback;
  const s = String(val).trim();
  const lower = s.toLowerCase();
  if (!s || ["nan", "null", "undefined", "na", "n/a", "-"].includes(lower)) return fallback;
  return s;
}

function normalizeDistrictName(value) {
  return String(value || "").trim().toUpperCase();
}

function districtToSlug(value) {
  return normalizeDistrictName(value).toLowerCase().replace(/\s+/g, "_");
}

function normalizeVillageLabel(value) {
  return String(value || "")
    .trim()
    .replace(/^\d+\s*[-._:/]?\s*/u, "")
    .replace(/\s+/g, " ");
}

function isPointGeometry(feature) {
  return String(feature?.geometry?.type || "").toLowerCase() === "point";
}

function normalizeRiskLevel(value, fallbackDepth = null) {
  const depth = Number(fallbackDepth);
  if (Number.isFinite(depth) && depth > 0) {
    return getRiskFromDepth(depth);
  }

  const text = String(value || "").trim().toLowerCase();
  if (["critical", "severe", "high"].includes(text)) return "critical";
  if (["warning", "medium", "moderate", "caution"].includes(text)) return "caution";
  if (["safe", "low", "good"].includes(text)) return "safe";

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
  if (normalized === "caution") return "#f59e0b";
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

function firstValidText(...values) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text) continue;
    const normalized = text.toLowerCase();
    if (["unknown", "na", "n/a", "null", "undefined", "-"].includes(normalized)) continue;
    return text;
  }
  return "NA";
}

function villageInfoHtml(feature, datasetRow = null, monthIndex = 0) {
  const props = feature?.properties || {};
  const row = datasetRow || {};
  
  // Robust GWL extraction
  const getGwl = () => {
    const depths = props.monthly_depths ?? row.monthly_depths;
    if (Array.isArray(depths) && depths.length > monthIndex) {
      const val = depths[monthIndex];
      if (Number.isFinite(val)) return val;
    }
    
    const candidates = [
      props.groundwater_estimate,
      props.predicted_groundwater_level,
      props.estimated_groundwater_depth,
      props.actual_last_month,
      props.depth,
      props.GW_Level,
      props.Predicted_GW_Level,
      row.actual_last_month,
      row.gw_level,
      row.predicted_groundwater_level,
      row.depth,
      row.GW_Level
    ];
    
    for (const cand of candidates) {
      const n = Number(cand);
      if (Number.isFinite(n) && n !== 0) return n;
    }
    
    // If we found a 0, return it as a last resort if it's explicitly there
    for (const cand of candidates) {
      if (cand === 0) return 0;
    }
    
    return NaN;
  };

  const gwl = getGwl();
  const normalizedRisk = normalizeRiskLevel(props.risk_level ?? row.risk_level, gwl);
  
  const mandal = cleanText(firstValidText(props.mandal, props.Mandal, props.MANDAL, props.mandal_name, row.mandal, row.Mandal, row.MANDAL), "NA").toUpperCase();
  const village = cleanText(firstValidText(props.village_name, props.Village_Name, props.VILLAGE, props.village, row.village_name, row.Village_Name, row.village), "NA");

  const villageId = row.village_id ?? row.Village_ID ?? props.village_id ?? props.Village_ID;
  const displayVillage = village && villageId && village !== String(villageId) ? `${village} (${villageId})` : village;

  const dataSource = props.data_source || (props.has_piezometer ? "Observed" : "Estimated");

  return `
    <div style="font-family: 'Inter', sans-serif; min-width: 170px; color: #e2e8f0; line-height: 1.5;">
      <strong style="color: #fff; font-size: 0.95rem; display: block; margin-bottom: 4px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">${displayVillage}</strong>
      <div style="color: #94a3b8; font-weight: 600; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">${mandal}</div>
      <div style="display: flex; flex-direction: column; gap: 2px;">
        <div><span style="color: #94a3b8;">Depth:</span> <strong style="color: #fff">${Number.isFinite(gwl) ? gwl.toFixed(2) + 'm' : "NA"}</strong></div>
        <div><span style="color: #94a3b8;">Status:</span> <span style="color: ${normalizedRisk === 'critical' ? '#fca5a5' : normalizedRisk === 'caution' ? '#fcd34d' : '#4ade80'}; font-weight: 700;">${normalizedRisk.toUpperCase()}</span></div>
        <div style="font-size: 0.65rem; color: #64748b; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">Source: <span style="color: #94a3b8;">${dataSource}</span></div>
      </div>
    </div>
  `;

}

function villageTooltipHtml(feature, datasetRow = null, monthIndex = 0, mapMode, baseMapTheme = 'prediction') {
  const props = feature?.properties || {};
  const row = datasetRow || {};
  const currentMode = (mapMode || "prediction").toLowerCase();
  
  const village = cleanText(firstValidText(
    props.village_name,
    props.Village_Name,
    props.VILLAGE,
    props.village,
    row.village_name,
    row.Village_Name,
    row.village
  ), "Unknown");
  
  const mandal = cleanText(firstValidText(
    props.mandal,
    props.Mandal,
    props.MANDAL,
    props.mandal_name,
    row.mandal,
    row.Mandal,
    row.mandal_name
  ), "Unknown");

  const district = cleanText(firstValidText(
    props.district,
    props.District,
    props.DISTRICT,
    props.district_name,
    row.district,
    row.District,
    row.district_name
  ), "Unknown");
  
  if (currentMode === "uncertainty") {
      const uncertainty = Number(props.uncertainty ?? row.uncertainty) || 1.0;
      const confidence = Number(props.confidence ?? props.confidence_score ?? row.confidence ?? row.confidence_score) || 0.87;
      return `
        <div style="min-width: 180px">
          <strong>Village:</strong> ${village}<br/>
          <strong>Mandal:</strong> ${mandal}<br/>
          <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.1); margin: 6px 0;"/>
          <strong>Uncertainty:</strong> ${uncertainty.toFixed(2)} m<br/>
          <strong>Confidence:</strong> ${(confidence * 100).toFixed(1)}%
        </div>
      `;
  }
  
  if (currentMode === "validation") {
      const hasSensor = !!(props.has_sensor || props.sensor_id || props.has_piezometer || row.has_sensor || row.sensor_id);
      if (!hasSensor) {
        return `
          <div style="min-width: 180px">
            <strong>Village:</strong> ${village}<br/>
            <strong>Mandal:</strong> ${mandal}<br/>
            <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.1); margin: 6px 0;"/>
            No sensor data for validation.
          </div>
        `;
      }
      
      const gwl = Number(
        props.monthly_depths?.[monthIndex] ?? 
        props.groundwater_estimate ?? 
        row?.gw_level ?? 
        row?.predicted_groundwater_level ?? 
        row?.depth ?? 
        NaN
      );
      const actual = Number(props.actual_last_month ?? row?.actual_last_month ?? row?.gw_level ?? row?.actual_groundwater_level ?? NaN);
      const error = Math.abs(gwl - actual);
      
      return `
        <div style="min-width: 180px">
          <strong>Village:</strong> ${village}<br/>
          <strong>Mandal:</strong> ${mandal}<br/>
          <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.1); margin: 6px 0;"/>
          <strong>Predicted:</strong> ${Number.isFinite(gwl) ? gwl.toFixed(2) : "NA"} m<br/>
          <strong>Actual:</strong> ${Number.isFinite(actual) ? actual.toFixed(2) : "NA"} m<br/>
          <strong>Error:</strong> ${Number.isFinite(error) ? error.toFixed(2) : "NA"} m
        </div>
      `;
  }
  
  return villageInfoHtml(feature, datasetRow, monthIndex);
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

async function readJsonIfValid(path) {
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const text = (await res.text()).trim();
    if (!text) return null;
    return JSON.parse(text);
  } catch {
    return null;
  }
}

const SURFACE_LAYER_STYLES = {
  canals: {
    lineColor: "#2563eb",
    lineWeight: 2.5,
    fillColor: "#60a5fa",
    fillOpacity: 0.08,
    dashArray: "5, 4"
  },
  streams: {
    lineColor: "#0891b2",
    lineWeight: 1.8,
    fillColor: "#22d3ee",
    fillOpacity: 0.18
  },
  drains: {
    lineColor: "#16a34a",
    lineWeight: 1.4,
    fillColor: "#4ade80",
    fillOpacity: 0.08,
    dashArray: "3, 5"
  },
  tanks: {
    lineColor: "#f59e0b",
    lineWeight: 1.2,
    fillColor: "#fbbf24",
    fillOpacity: 0.2
  },
  contours: {
    lineColor: "#7c4a2d",
    lineWeight: 0.8,
    opacity: 0.65
  }
};

function formatLengthKm(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric.toFixed(2)} km` : "NA";
}

function formatAreaSqKm(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric.toFixed(2)} km²` : "NA";
}

function surfaceLayerStyle(layerKey, feature) {
  const config = SURFACE_LAYER_STYLES[layerKey] || SURFACE_LAYER_STYLES.canals;
  const geomType = String(feature?.geometry?.type || "").toLowerCase();
  const isPolygon = geomType.includes("polygon");
  if (layerKey === "contours") {
    return {
      color: config.lineColor,
      weight: config.lineWeight,
      opacity: config.opacity,
      fillOpacity: 0
    };
  }
  if (isPolygon) {
    return {
      color: config.lineColor,
      weight: config.lineWeight,
      fillColor: config.fillColor,
      fillOpacity: config.fillOpacity,
      opacity: 0.95
    };
  }
  return {
    color: config.lineColor,
    weight: config.lineWeight,
    opacity: 0.95,
    dashArray: config.dashArray,
    fillOpacity: 0
  };
}

function surfaceLayerTooltip(layerKey, feature) {
  const props = feature?.properties || {};
  const label = firstValidText(
    props.feature_label,
    props.canal_name,
    props.project_name,
    props.river_name,
    props.sub_river,
    props.drain_name,
    props.description,
    props.tank_name,
    props.district_name,
    props.region_name,
    `Feature`
  );

  const getRow = (title, val) => {
    const text = String(val ?? "").trim();
    if (!text || text.toLowerCase() === "na" || text === "-") return "";
    return `<div><span style="color: #94a3b8; font-weight: 600;">${title}:</span> <span style="color: #fff;">${text}</span></div>`;
  };

  const getVal = (title, val, formatter) => {
    if (!Number.isFinite(Number(val))) return "";
    return `<div><span style="color: #94a3b8; font-weight: 600;">${title}:</span> <span style="color: #fff;">${formatter(val)}</span></div>`;
  };

  let body = "";
  if (layerKey === "canals") {
    body += getRow("Project", firstValidText(props.project_name, ""));
    body += getRow("Code", firstValidText(props.canal_code, props.project_code, ""));
    body += getRow("Type", firstValidText(props.canal_type, ""));
    body += getVal("Length", props.length_km, formatLengthKm);
  } else if (layerKey === "streams") {
    body += getRow("River", firstValidText(props.river_name, ""));
    body += getRow("Sub-river", firstValidText(props.sub_river, ""));
    body += getVal("Area", props.area_sqkm, formatAreaSqKm);
    body += getVal("Length", props.length_km, formatLengthKm);
  } else if (layerKey === "drains") {
    body += getRow("Description", firstValidText(props.description, ""));
    body += getRow("Code", firstValidText(props.drain_code, ""));
    body += getVal("Length", props.length_km, formatLengthKm);
  } else if (layerKey === "tanks") {
    body += getRow("District", firstValidText(props.district_name, ""));
    body += getRow("Region", firstValidText(props.region_name, ""));
    body += getVal("Area", props.area_sqkm, formatAreaSqKm);
    body += getVal("Perimeter", props.length_km, formatLengthKm);
  } else {
    body += getRow("Elevation", firstValidText(props.contour_label, props.elevation_m, ""));
  }

  return `
    <div style="min-width: 160px; font-family: 'Inter', sans-serif; color: #e2e8f0; line-height: 1.4;">
      <strong style="color: #fff; font-size: 0.95rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">${label}</strong>
      <div style="display: flex; flex-direction: column; gap: 2px;">
        ${body}
      </div>
    </div>
  `;
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

function FitToFilterSelection({ filteredGeojson, filters, stateBoundaryLayer }) {
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

    const stateOnly = Boolean(filters?.state) && !filters?.district;
    const districtOnly = Boolean(filters?.district) && !filters?.mandal && !filters?.villageName;

    if (stateOnly && stateBoundaryLayer && String(filters?.state).toUpperCase() === "ANDHRA PRADESH") {
      dataToFit = stateBoundaryLayer;
      padding = 0.05;
      maxZoom = 7.5;
    } else if (filters?.district) {
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

function NtrVillageClickFallback({ filteredGeojson, selectedDistrictNorm, onVillageClick }) {
  useMapEvents({
    click(event) {
      console.log("Map click detected in NTR district fallback", { selectedDistrictNorm });
      if (selectedDistrictNorm !== "NTR") return;
      const pointFeatures = (filteredGeojson?.features || []).filter(
        (feature) => String(feature?.geometry?.type || "").toLowerCase() === "point"
      );
      console.log(`Found ${pointFeatures.length} point features in NTR district`);
      if (!pointFeatures.length) return;

      let nearestFeature = null;
      let nearestDistance = Number.POSITIVE_INFINITY;
      pointFeatures.forEach((feature) => {
        const coordinates = feature?.geometry?.coordinates;
        if (!Array.isArray(coordinates) || coordinates.length < 2) return;
        const lon = Number(coordinates[0]);
        const lat = Number(coordinates[1]);
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
        const distance = event.latlng.distanceTo(L.latLng(lat, lon));
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearestFeature = feature;
        }
      });

      if (nearestFeature) {
        console.log("Nearest feature found:", nearestFeature.properties?.village_name);
        onVillageClick(nearestFeature);
      }
    }
  });

  return null;
}

function RegionalLabels({ filters }) {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());

  useEffect(() => {
    const handleZoom = () => setZoom(map.getZoom());
    map.on('zoomend', handleZoom);
    return () => map.off('zoomend', handleZoom);
  }, [map]);

  // Major AP Districts with rough coordinates
  const districts = [
    { name: "Visakhapatnam", lat: 17.6868, lng: 83.2185 },
    { name: "Vijayawada", lat: 16.5062, lng: 80.6480 },
    { name: "Guntur", lat: 16.3067, lng: 80.4365 },
    { name: "Tirupati", lat: 13.6285, lng: 79.4192 },
    { name: "Kurnool", lat: 15.8281, lng: 78.0373 },
    { name: "Anantapur", lat: 14.6819, lng: 77.6006 },
    { name: "Nellore", lat: 14.4426, lng: 79.9865 },
    { name: "Kakinada", lat: 16.9891, lng: 82.2475 },
    { name: "Kadapa", lat: 14.4673, lng: 78.8242 }
  ];

  // Only show labels when zoomed out enough, or if a district is specifically filtered
  if (zoom > 12) return null;

  return (
    <>
      {districts.map(d => (
        <Marker 
          key={d.name} 
          position={[d.lat, d.lng]} 
          icon={L.divIcon({
            className: 'regional-label',
            html: `<div style="
              color: rgba(255,255,255,0.6);
              font-size: ${zoom > 8 ? '0.85rem' : '0.7rem'};
              font-weight: 600;
              text-transform: uppercase;
              letter-spacing: 0.1em;
              white-space: nowrap;
              pointer-events: none;
              text-shadow: 0 2px 4px rgba(0,0,0,0.5);
            ">${d.name}</div>`,
            iconSize: [0, 0]
          })}
        />
      ))}
    </>
  );
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
  showRechargeZones,
  villageDataError,
  villageDataSource,
  datasetRowsById,
  datasetRowsByLocation,
  anomalies,
  rechargeZones,
  selectedDistrict,
  showRainfall,
  showCanals,
  showStreams,
  showDrains,
  showTanks,
  showDemSurface,
  mapMode,
  baseMapTheme,
  showStateBoundary,
  stateBoundaryLayer,
  showAquifer,
  showSoil,
  showAnomalies
}) {
  const [hoverBadge, setHoverBadge] = useState(null);
  const [hoveredDistrictName, setHoveredDistrictName] = useState(null);
  const [aquiferGeojson, setAquiferGeojson] = useState(null);
  const [piezometerStations, setPiezometerStations] = useState([]);
  const [surfaceLayers, setSurfaceLayers] = useState({
    canals: null,
    streams: null,
    drains: null,
    tanks: null,
    demMeta: null,
    demContours: null
  });
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
    const classStr = String(props.Geo_Class || props.aquifer_type || props.AQUI_CODE || "Aquifer unit").trim();
    const codeStr = String(props.AQUI_CODE || "").trim().toLowerCase();
    const lower = classStr.toLowerCase();

    if (lower === "al" || lower.includes("alluv") || codeStr === "al") {
      return { label: "Alluvium", color: "#7DD3FC" };
    }
    
    if (
      lower.includes("shale") ||
      lower.includes("sand stone") ||
      lower.includes("sandstone") ||
      lower.includes("lime stone") ||
      lower.includes("limestone") ||
      codeStr === "st" ||
      codeStr === "ls" ||
      codeStr === "sh"
    ) {
      return { label: "Fractured Rock", color: "#FB923C" };
    }

    // Default for KH (Khondalite), Charnockite, Gneiss, etc.
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
    const dName = String(props.district ?? props.District ?? props.DISTRICT ?? props.district_name ?? "").trim();
    const mName = String(props.mandal ?? props.Mandal ?? props.MANDAL ?? props.mandal_name ?? "").trim();
    const vName = String(props.village_name ?? props.Village_Name ?? props.VILLAGE ?? props.NAME ?? "").trim();
    const villageId = Number(props.village_id ?? props.Village_ID ?? props.ID);
    const locationKey = buildLocationKey(dName, mName, vName);
    const row =
      (locationKey && datasetRowsByLocation?.get(locationKey)) ||
      (selectedDistrictNorm !== "KRISHNA" && Number.isFinite(villageId) ? datasetRowsById?.get(villageId) : null);
    
    const villageName = vName || row?.village_name || "Unknown Village";
    const district = dName || row?.district || selectedDistrict || "Unknown";
    const mandal = mName || row?.mandal || "Unknown";
    const rawType = String(props.anomaly_type || props.type || props.reason || "Normal");
    const anomalyClass = anomalyMeta(feature).label;
    const deviation = Number(props.deviation_m ?? props.anomaly_score);
    const currentGroundwater = Number(
      row?.gw_level ?? 
      row?.actual_last_month ?? 
      row?.predicted_groundwater_level ?? 
      row?.depth ?? 
      props.groundwater_estimate ?? 
      props.depth ?? 
      NaN
    );
    const displayVillage = villageName && villageId && villageName !== String(villageId) ? `${villageName} (${villageId})` : villageName;
    return `
      <div style="min-width: 190px; font-family: 'Inter', sans-serif; color: #e2e8f0; line-height: 1.5;">
        <strong style="color: #ef4444; font-size: 0.9rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(239, 68, 68, 0.2); padding-bottom: 4px;">Hydrogeological Anomaly</strong>
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <div><span style="color: #94a3b8; font-weight: 600;">Village:</span> <span style="color: #fff;">${displayVillage}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">District:</span> <span style="color: #fff;">${district}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Mandal:</span> <span style="color: #fff;">${mandal}</span></div>
          <div style="margin-top: 4px;"><span style="color: #94a3b8; font-weight: 600;">Deviation:</span> <span style="color: #fca5a5; font-weight: 700;">${Number.isFinite(deviation) ? `${deviation.toFixed(2)} m` : "NA"}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Type:</span> <span style="color: #fff; font-weight: 600;">${anomalyClass}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Current GWL:</span> <span style="color: #fff;">${Number.isFinite(currentGroundwater) ? `${currentGroundwater.toFixed(2)} m` : "NA"}</span></div>
        </div>
      </div>
    `;
  };

  useEffect(() => {
    let active = true;
    (async () => {
      const districtSlug = districtToSlug(selectedDistrict);
      const preferredPaths = (districtSlug === "krishna" || !districtSlug || districtSlug === "andhra_pradesh")
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
      const [canals, streams, drains, tanks, demMeta, demContours] = await Promise.all([
        readGeoJsonIfValid("/data/krishna_canals.geojson"),
        readGeoJsonIfValid("/data/krishna_streams.geojson"),
        readGeoJsonIfValid("/data/krishna_drains.geojson"),
        readGeoJsonIfValid("/data/krishna_tanks.geojson"),
        readJsonIfValid("/data/krishna_dem_meta.json"),
        readGeoJsonIfValid("/data/krishna_dem_contours.geojson")
      ]);
      if (!active) return;
      setSurfaceLayers({
        canals,
        streams,
        drains,
        tanks,
        demMeta,
        demContours
      });
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const districtSlug = districtToSlug(selectedDistrict);
        let candidatePaths = [];
        
        if (districtSlug === "krishna") {
          candidatePaths = ["/data/krishna_piezometers.json"];
        } else if (districtSlug === "ntr") {
          candidatePaths = ["/data/ntr_piezometers.json"];
        } else {
          // Default: load all available piezometer datasets
          candidatePaths = ["/data/krishna_piezometers.json", "/data/ntr_piezometers.json"];
        }

        let allStations = [];
        for (const path of candidatePaths) {
          try {
            const response = await fetch(path, { headers: { Accept: "application/json" } });
            if (!response.ok) continue;
            const payload = await response.json();
            const stations = Array.isArray(payload?.stations) ? payload.stations : [];
            allStations = [...allStations, ...stations];
          } catch (e) {
            console.warn(`Failed to fetch piezometers from ${path}`, e);
          }
        }
        
        if (!active) return;

        const filtered = allStations.filter((station) => {
          const lat = Number(station?.latitude ?? station?.lat);
          const lon = Number(station?.longitude ?? station?.lon ?? station?.lng);
          const hasCoords = Number.isFinite(lat) && Number.isFinite(lon);
          if (!hasCoords) return false;
          
          // If a specific district is selected, filter by it. 
          // "ANDHRA PRADESH" or empty string means "show all for the state"
          const sDist = normalizeDistrictName(selectedDistrict);
          if (sDist && sDist.toUpperCase() !== "ANDHRA PRADESH" && sDist.toUpperCase() !== "AP") {
            const stationDist = normalizeDistrictName(station?.district);
            return stationDist === sDist;
          }
          return true;
        });
        
        setPiezometerStations(filtered);
      } catch (err) {
        console.error("Error in piezometer fetch effect:", err);
        if (active) setPiezometerStations([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedDistrict, selectedDistrictNorm]);

  const visibleFeatures = filteredGeojson;

  const extrusionGeojson = useMemo(() => {
    if (!visibleFeatures || !is3D) return null;
    const features = visibleFeatures.features
      .filter((f) => !isPointGeometry(f))
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
  }, [visibleFeatures, is3D]);

  const groundwaterStyle = (feature) => {
    const isSelected = isSelectedVillageFeature(feature);
    const props = feature?.properties || {};
    const villageId = Number(props.village_id);
    const locationKey = buildLocationKey(props.district, props.mandal, props.village_name);
    const row =
      (locationKey && datasetRowsByLocation?.get(locationKey)) ||
      (selectedDistrictNorm !== "KRISHNA" && Number.isFinite(villageId) ? datasetRowsById?.get(villageId) : null);

    const rawDepth =
      props.monthly_depths?.[monthIndex] ??
      props.groundwater_estimate ??
      props.actual_last_month ??
      row?.actual_last_month ?? 
      row?.gw_level ?? 
      row?.predicted_groundwater_level ?? 
      row?.depth ?? 
      props.depth ??
      null;
    const depth = Number(rawDepth);
    const hasDepth = Number.isFinite(depth);
    const normalized = hasDepth ? normalizeRiskLevel(props.risk_level, depth) : "unknown";
    // Map Mode & Overlay Logic
    let fillColor = "#9ca3af";
    const currentMode = (mapMode || "prediction").toLowerCase();

    if (showLulc) {
        const category = String(props.lulc_2021_dominant || props.lulc || "unclassified").toLowerCase();
        fillColor = LULC_COLORS[category] || LULC_COLORS.unclassified;
    } else if (showSoil) {
        const soil = String(props.soil_type || props.soil || "").toLowerCase();
        if (soil.includes("red")) fillColor = "#EF4444";
        else if (soil.includes("black")) fillColor = "#1E293B";
        else if (soil.includes("alluv")) fillColor = "#F59E0B";
        else if (soil.includes("clay")) fillColor = "#B45309";
        else fillColor = "#94A3B8";
    } else if (showGroundwaterLevels || currentMode === "depth") {
        const depth = Number(rawDepth || 0);
        const [r, g, b] = healthColor(depth);
        fillColor = `rgb(${r}, ${g}, ${b})`;
    } else if (currentMode === "trend") {
        const trend = String(props.trend || props.trend_direction || "").toLowerCase();
        if (trend.includes("declin")) fillColor = "#ef4444";
        else if (trend.includes("ris") || trend.includes("increas")) fillColor = "#3b82f6";
        else fillColor = "#facc15";
    } else {
        // Default Risk colors using unified logic
        const depth = Number(rawDepth || 0);
        const normalized = normalizeRiskLevel(props.risk_level, depth);
        if (normalized === "critical") fillColor = "#ef4444";
        else if (normalized === "caution") fillColor = "#f59e0b";
        else fillColor = "#22c55e";
    }


    const hasSensor = !!(props.has_sensor === 1 || props.has_sensor === true || props.sensor_id);
    
    // 1. COMBINED RELIABILITY (Physics + AI Confidence)
    // High reliability (near sensor OR low GNN uncertainty) -> Solid color
    // Low reliability (far AND high uncertainty) -> Faded color
    const reliability = Number(props.combined_reliability ?? 0.8);
    const finalOpacity = hasSensor ? 0.92 : (0.35 + 0.6 * reliability);
    
    // 2. SENSOR GAP DETECTION (Policy Priority)
    const gapScore = Number(props.gap_score || 0);
    const isGapZone = gapScore > 0.75 && !hasSensor;
    
    return {
      // Teachers (Sensors) get Cyan, Gaps get Red, Students get faint/no border
      color: isSelected ? "#fff" : (hasSensor ? "#00e5ff" : (isGapZone ? "#f43f5e" : "rgba(255, 255, 255, 0.05)")),
      weight: isSelected ? 2.5 : (hasSensor ? 3.0 : (isGapZone ? 2.5 : 0.5)),
      fillColor: fillColor,
      fillOpacity: isSelected ? 0.95 : finalOpacity,
      className: hasSensor ? 'premium-village-polygon sensor-village' : (isGapZone ? 'premium-village-polygon gap-zone' : 'premium-village-polygon'),
      // Only dash Student nodes if reliability is critically low, otherwise keep them clean
      dashArray: hasSensor ? "" : (isGapZone ? "4, 6" : (reliability < 0.3 ? "3, 10" : ""))
    };
  };

  const neutralVillageStyle = (feature) => {
    const isSelected = isSelectedVillageFeature(feature);
    return {
      color: isSelected ? "#fff" : "rgba(255, 255, 255, 0.1)",
      weight: isSelected ? 2 : 0.5,
      fillColor: isSelected ? "rgba(0, 229, 255, 0.2)" : "transparent",
      fillOpacity: isSelected ? 0.4 : 0,
      className: 'premium-village-polygon-neutral',
      dashArray: ""
    };
  };

  const selectedVillageStyle = (feature) => groundwaterStyle(feature);

  const isSelectedVillageFeature = (feature) => {
    if (!feature || !selectedFeature) return false;
    
    // Primary check: Location Key (District + Mandal + Village)
    const featureKey = buildLocationKey(
      feature?.properties?.district ?? feature?.properties?.District,
      feature?.properties?.mandal ?? feature?.properties?.Mandal,
      feature?.properties?.village_name ?? feature?.properties?.Village_Name ?? feature?.properties?.VILLAGE
    );
    const selectedKey = buildLocationKey(
      selectedFeature?.properties?.district,
      selectedFeature?.properties?.mandal,
      selectedFeature?.properties?.village_name
    );
    
    if (featureKey && selectedKey && featureKey === selectedKey) return true;

    // Secondary check: Village ID (only if location keys are unavailable or don't match)
    const featureVillageId = Number(feature?.properties?.village_id ?? feature?.properties?.ID);
    const selectedVillageId = Number(selectedFeature?.properties?.village_id);
    if (Number.isFinite(featureVillageId) && Number.isFinite(selectedVillageId)) {
      return featureVillageId === selectedVillageId;
    }

    return false;
  };

  const extrusionStyle = (feature) => {
    const props = feature?.properties || {};
    const villageId = Number(props.village_id);
    const locationKey = buildLocationKey(props.district, props.mandal, props.village_name);
    const row =
      (locationKey && datasetRowsByLocation?.get(locationKey)) ||
      (selectedDistrictNorm !== "KRISHNA" && Number.isFinite(villageId) ? datasetRowsById?.get(villageId) : null);

    const monthly = props.monthly_depths || [];
    const depth = Number(
      monthly[monthIndex] ?? 
      props.groundwater_estimate ??
      props.actual_last_month ??
      row?.actual_last_month ??
      row?.gw_level ??
      row?.predicted_groundwater_level ??
      row?.depth ??
      props.depth ?? 
      0
    );
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
    if (!showAnomalies || !anomalies || !isValidGeoJSON(anomalies)) return null;
    const selected = Array.isArray(selectedAnomalyTypes) ? selectedAnomalyTypes : [];
    const allowedVillageIds = new Set(
      (visibleFeatures?.features || [])
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
  }, [anomalies, selectedAnomalyTypes, selectedDistrictNorm, visibleFeatures]);

  const severeAnomalyHighlightGeojson = useMemo(() => {
    if (!visibleFeatures?.features?.length || !visibleAnomalies?.features?.length) return null;
    const severeSelected = Array.isArray(selectedAnomalyTypes) && selectedAnomalyTypes.includes("Severe drop");
    if (!severeSelected) return null;
    const severeVillageIds = new Set(
      visibleAnomalies.features
        .filter((feature) => anomalyMeta(feature).label === "Severe drop")
        .map((feature) => Number(feature?.properties?.village_id))
        .filter((value) => Number.isFinite(value))
    );
    if (!severeVillageIds.size) return null;
    const features = visibleFeatures.features.filter((feature) => severeVillageIds.has(Number(feature?.properties?.village_id)));
    if (!features.length) return null;
    return { type: "FeatureCollection", features };
  }, [visibleFeatures, selectedAnomalyTypes, visibleAnomalies]);

  const anomalyEmptyState = Boolean(anomalies && isValidGeoJSON(anomalies) && Array.isArray(selectedAnomalyTypes) && selectedAnomalyTypes.length === 0);

  const lulcGeojson = useMemo(() => {
    if (!showLulc || !visibleFeatures?.features?.length) return null;
    const selected = (selectedLulcClasses || []).map((item) => String(item));
    const selectedSet = new Set(selected);
    if (selectedSet.size === 0) {
      return { ...visibleFeatures, features: [] };
    }
    return {
      ...visibleFeatures,
      features: visibleFeatures.features
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
  }, [visibleFeatures, showLulc, selectedLulcClasses]);

  const lulc3DGeojson = useMemo(() => {
    if (!is3D || !lulcGeojson?.features?.length) return null;
    const features = lulcGeojson.features
      .filter((feature) => !isPointGeometry(feature))
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

  const rechargeZonesGeojson = useMemo(() => {
    if (!showRechargeZones || !visibleFeatures?.features?.length) return null;
    const features = visibleFeatures.features
      .map(f => {
        const meta = calculateAdvancedRechargePriority(f.properties);
        return {
          ...f,
          properties: {
            ...f.properties,
            __rechargePriority: meta.priority,
            __rechargeColor: meta.color,
            __rechargeLabel: meta.label,
            __rechargeScore: meta.score,
            __rechargeMeta: meta
          }
        };
      })
      .filter(f => f.properties.__rechargePriority > 0);
    return { type: "FeatureCollection", features };
  }, [visibleFeatures, showRechargeZones]);

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
          coordinates: [
            Number(station.longitude ?? station.lon ?? station.lng), 
            Number(station.latitude ?? station.lat)
          ]
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
      <div style="min-width: 180px; font-family: 'Inter', sans-serif; color: #e2e8f0; line-height: 1.5;">
        <strong style="color: #00e5ff; font-size: 0.9rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(0, 229, 255, 0.2); padding-bottom: 4px;">Piezometer Station</strong>
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <div><span style="color: #94a3b8; font-weight: 600;">Station:</span> <span style="color: #fff;">${props.id || "NA"}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Village:</span> <span style="color: #fff;">${props.village || props.village_name || "NA"}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Latest GWL:</span> <span style="color: #34d399; font-weight: 700;">${Number.isFinite(latestValue) ? `${latestValue.toFixed(2)} m` : "NA"}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Obs. Depth:</span> <span style="color: #fff;">${Number.isFinite(totalDepth) ? `${totalDepth.toFixed(2)} m` : "NA"}</span></div>
          <div><span style="color: #94a3b8; font-weight: 600;">Observations:</span> <span style="color: #fff;">${observationCount ?? "NA"}</span></div>
          <div style="font-size: 0.7rem; color: #64748b; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">Latest Reading: ${latestLabel}</div>
        </div>
      </div>
    `;
  };

  const wellsData = useMemo(() => {
    if (!showWells || !visibleFeatures?.features?.length) return null;
    const data = visibleFeatures.features.map((feature) => {
      const props = feature?.properties || {};
      const key = buildLocationKey(props.district, props.mandal, props.village_name);
      
      const villageId = Number(props.village_id);
      const datasetRow = (Number.isFinite(villageId) ? datasetRowsById?.get(villageId) : null) || (key && datasetRowsByLocation?.get(key));
      
      const effectiveProps = { ...props, ...(datasetRow || {}) };
      
      let lat = Number(effectiveProps.centroid_lat);
      let lon = Number(effectiveProps.centroid_lon);
      
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
         if (feature.geometry?.type === "Point") {
            lon = feature.geometry.coordinates[0];
            lat = feature.geometry.coordinates[1];
         } else if (feature.geometry?.type === "Polygon" || feature.geometry?.type === "MultiPolygon") {
            const bounds = L.geoJSON(feature).getBounds();
            const center = bounds.getCenter();
            lat = center.lat;
            lon = center.lng;
         }
      }

      const wellsTotal = Number(effectiveProps.wells_total);
      const functioning = Number(effectiveProps.pumping_functioning_wells);
      
      let wells = Number.isFinite(wellsTotal) && wellsTotal > 0 
        ? wellsTotal 
        : (Number.isFinite(functioning) ? functioning : 0);
        
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || wells <= 0) return null;

      return {
        lat,
        lng: lon,
        well_count: wells,
        village: effectiveProps.village_name || effectiveProps.village || "Unknown",
        district: effectiveProps.district || "Unknown",
        feature // Reference for selection logic
      };
    }).filter(Boolean);
    
    return data;
  }, [showWells, visibleFeatures, datasetRowsByLocation, datasetRowsById]);

  const districtNote = useMemo(() => {
    if (selectedDistrictNorm === "NTR") {
      return "NTR: point-based village layer only";
    }
    return null;
  }, [selectedDistrictNorm]);

const baseTileUrl = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

  const baseTileAttribution =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  return (
    <>
      {!visibleFeatures?.features?.length && (
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
              ? "All villages have been hidden by your current filter selections. Try adjusting the risk levels or location filters."
              : villageDataError || "No real village polygons are loaded."}
          </div>
        <div
          style={{
            position: "absolute",
            zIndex: 600,
            right: "18px",
            top: "125px", // Positioned below the other possible info boxes
            maxWidth: "360px",
            background: "rgba(8, 15, 24, 0.92)",
            border: "1px solid rgba(0, 229, 255, 0.45)",
            color: "#dbeafe",
            borderRadius: "10px",
            padding: "10px 12px",
            fontSize: "0.78rem",
            lineHeight: 1.45,
            backdropFilter: "blur(2px)",
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)"
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span style={{ color: '#00e5ff', fontSize: '1.1rem' }}>●</span>
            <strong style={{ color: '#fff' }}>Sensor Network Density</strong>
          </div>
          <div style={{ color: '#94a3b8' }}>
            {(() => {
              const features = filteredGeojson?.features || [];
              const sensorCount = features.filter(f => !!(f.properties?.has_sensor === 1 || f.properties?.has_sensor === true || f.properties?.sensor_id)).length;
              const total = features.length;
              const ratio = total > 0 ? (total / Math.max(sensorCount, 1)).toFixed(1) : 0;
              return (
                <>
                  <div>Active Physical Sensors: <span style={{ color: '#00e5ff', fontWeight: 600 }}>{sensorCount}</span></div>
                  <div>Total Villages Covered: <span style={{ color: '#fff', fontWeight: 600 }}>{total}</span></div>
                  <div style={{ marginTop: '4px', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '4px', fontStyle: 'italic' }}>
                    Network Ratio: ~1 sensor per {ratio} villages
                  </div>
                </>
              );
            })()}
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            zIndex: 600,
            right: "18px",
            bottom: "30px",
            maxWidth: "260px",
            background: "rgba(8, 15, 24, 0.95)",
            border: "1px solid rgba(148, 163, 184, 0.3)",
            color: "#dbeafe",
            borderRadius: "10px",
            padding: "10px 12px",
            fontSize: "0.7rem",
            backdropFilter: "blur(6px)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.4)"
          }}
        >
          <strong style={{ display: 'block', marginBottom: '6px', fontSize: '0.8rem', color: '#fff', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '4px' }}>
            System Validation (MAE)
          </strong>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span style={{ color: '#00e5ff', fontWeight: 600 }}>● GNN (Spatial AI):</span>
            <span style={{ fontWeight: 600 }}>3.69m</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px', opacity: 0.8 }}>
            <span>● IDW Baseline:</span>
            <span>3.50m</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px', opacity: 0.8 }}>
            <span>● XGBoost:</span>
            <span>5.70m</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', opacity: 0.8 }}>
            <span>● Global Mean:</span>
            <span>4.68m</span>
          </div>
          
          <div style={{ background: 'rgba(34, 197, 94, 0.1)', padding: '6px', borderRadius: '4px', border: '1px solid rgba(34, 197, 94, 0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', color: '#22c55e', fontWeight: 'bold' }}>
              <span>Interval Coverage:</span>
              <span>88.9%</span>
            </div>
            <div style={{ fontSize: '0.6rem', color: '#4ade80', marginTop: '2px' }}>
              Target: 90% (Calibrated Uncertainty)
            </div>
          </div>
        </div>

        {!villageDataSource && (
            <div style={{ marginTop: "6px", color: "#93c5fd" }}>
              Add your file at <code>/frontend/public/data/village_boundaries.geojson</code>.
            </div>
          )}
        </div>
      )}
      <MapContainer
        key={`map-instance-${is3D ? "3d" : "2d"}`}
        id="dashboard-leaflet-map"
        center={[INITIAL_VIEW_STATE.latitude, INITIAL_VIEW_STATE.longitude]}
        zoom={INITIAL_VIEW_STATE.zoom}
        style={{ height: "100%", width: "100%", background: "#0f172a" }}
        zoomControl={false}
        preferCanvas={true}
      >
        <TileLayer attribution={baseTileAttribution} url={baseTileUrl} />

        {showDemSurface && surfaceLayers.demMeta?.bounds && (
          <ImageOverlay
            url={surfaceLayers.demMeta.hillshade || "/data/krishna_dem_hillshade.png"}
            bounds={surfaceLayers.demMeta.bounds}
            opacity={0.58}
            interactive={false}
          />
        )}

        {extrusionGeojson && <GeoJSON key={`3d-${monthIndex}`} data={extrusionGeojson} style={extrusionStyle} interactive={false} />}
{(filters?.state || showStateBoundary) && stateBoundaryLayer && (
          <GeoJSON
            key={`state-boundary-${filters?.state || "none"}`}
            data={stateBoundaryLayer}
            style={() => {
              const isHighlighted = (filters?.state && String(filters.state).trim().toUpperCase() === "ANDHRA PRADESH");
              return {
                color: isHighlighted ? "#000000" : "#64748b",
                weight: isHighlighted ? 3.5 : 2.0,
                fillColor: "transparent",
                fillOpacity: 0,
                dashArray: isHighlighted ? "" : "5, 5"
              };
            }}
            interactive={false}
          />
        )}

        {visibleFeatures && (
          <GeoJSON
            key={`2d-${monthIndex}`}
            data={visibleFeatures}
            style={(feature) => {
              if (isSelectedVillageFeature(feature)) {
                return selectedVillageStyle(feature);
              }
              return showGroundwaterLevels ? groundwaterStyle(feature) : neutralVillageStyle(feature);
            }}
            eventHandlers={villageEvents}
            pointToLayer={(feature, latlng) => (isPointGeometry(feature) ? villagePointToLayer(feature, latlng) : undefined)}
            onEachFeature={(feature, layer) => {
              const props = feature?.properties || {};
              const villageId = Number(props.village_id);
              const locationKey = buildLocationKey(props.district, props.mandal, props.village_name);
              const datasetRow =
                (Number.isFinite(villageId) ? datasetRowsById?.get(villageId) : null) ||
                (locationKey && datasetRowsByLocation?.get(locationKey));
              const popupHtml = villageTooltipHtml(feature, datasetRow, monthIndex, mapMode,
  baseMapTheme);
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
        {(filters?.state || showDistrictBoundaries) && visibleFeatures && (
          <GeoJSON
            data={visibleFeatures}
            style={(feature) => {
              const district = String(feature?.properties?.district || "District");
              const color = boundaryColorFromText(district);
              return {
                color: "#000000",
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
        {showMandalBoundaries && visibleFeatures && (
          <GeoJSON
            data={visibleFeatures}
            style={(feature) => {
              const mandal = String(feature?.properties?.mandal || "Mandal");
              const color = boundaryColorFromText(mandal);
              return {
                color: "#000000",
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
            pointToLayer={(feature, latlng) => {
              const category = feature?.properties?.__lulcCategory || "unclassified";
              const color = LULC_COLORS[category] || LULC_COLORS.unclassified;
              return L.circleMarker(latlng, {
                radius: 5.2,
                color: "#1e293b",
                weight: 1,
                fillColor: color,
                fillOpacity: is3D ? 0.12 : 0.6
              });
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
              const village = p.village_name || p.VILLAGE || "Village";
              const d11 = p.lulc_2011_dominant;
              const d21 = p.lulc_2021_dominant;
              const delta = p.lulc_change;
              
              let extraInfo = "";
              if (d11 && d21 && d11 !== "NA") {
                extraInfo = `<div style="color: #94a3b8; font-size: 0.7rem; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 4px;">
                  Historical: ${d11} → ${d21}
                </div>`;
              }

              layer.bindTooltip(`
                <div style="font-family: 'Inter', sans-serif; min-width: 150px; color: #e2e8f0; line-height: 1.5; padding: 4px;">
                  <strong style="color: #fff; font-size: 0.9rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">${village}</strong>
                  <div style="display: flex; flex-direction: column; gap: 2px;">
                    <div><span style="color: #94a3b8; font-weight: 600;">LULC:</span> <span style="color: #00e5ff; font-weight: 600;">${labelMap[category] || "Unclassified"}</span></div>
                    ${extraInfo}
                  </div>
                </div>
              `, { sticky: true, opacity: 0.98 });
            }}
          />
        )}

        {rechargeZonesGeojson && isValidGeoJSON(rechargeZonesGeojson) && (
          <GeoJSON 
            key={`recharge-${showRechargeZones}`}
            data={rechargeZonesGeojson} 
            style={(feature) => ({
              color: feature.properties.__rechargeColor,
              weight: feature.properties.__rechargePriority === 1 ? 4 : 2,
              dashArray: feature.properties.__rechargePriority === 1 ? '' : '5, 5',
              fillColor: feature.properties.__rechargeColor,
              fillOpacity: feature.properties.__rechargePriority === 1 ? 0.25 : 0.1,
              className: feature.properties.__rechargePriority === 1 ? 'recharge-priority-high' : ''
            })}
            onEachFeature={(feature, layer) => {
              const p = feature.properties;
              layer.bindTooltip(`
                <div style="font-family: 'Inter', sans-serif; padding: 6px;">
                  <strong style="color: #fff; font-size: 0.85rem;">${p.village_name || 'Village'}</strong><br/>
                  <span style="color: ${p.__rechargeColor}; font-weight: 800;">${p.__rechargeLabel}</span>
                </div>
              `, { sticky: true, opacity: 0.98 });
            }}
          />
        )}

        {showSoil && visibleFeatures && (
          <GeoJSON
            key="soil-layer"
            data={visibleFeatures}
            style={(feature) => {
              const soil = String(feature?.properties?.soil_type || feature?.properties?.soil || "Other").toLowerCase();
              let color = "#CBD5E1";
              if (soil.includes("red")) color = "#EF4444";
              else if (soil.includes("black")) color = "#1E293B";
              else if (soil.includes("alluv")) color = "#F59E0B";
              else if (soil.includes("clay")) color = "#B45309";
              return {
                fillColor: color,
                weight: 0.6,
                opacity: 0.4,
                color: "rgba(255,255,255,0.4)",
                fillOpacity: 0.7
              };
            }}
            onEachFeature={(feature, layer) => {
              const p = feature?.properties || {};
              const village = p.village_name || p.VILLAGE || "Village";
              const soil = p.soil_type || p.soil || "NA";
              layer.bindTooltip(`
                <div style="font-family: 'Inter', sans-serif; min-width: 150px; color: #e2e8f0; line-height: 1.5; padding: 4px;">
                  <strong style="color: #fff; font-size: 0.9rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">${village}</strong>
                  <div style="display: flex; flex-direction: column; gap: 2px;">
                    <div><span style="color: #94a3b8; font-weight: 600;">Soil Type:</span> <span style="color: #fbbf24; font-weight: 600;">${soil}</span></div>
                  </div>
                </div>
              `, { sticky: true, opacity: 0.98 });
            }}
          />
        )}

        {showRainfall && visibleFeatures && (
          <GeoJSON
            key={`rainfall-${monthIndex}`}
            data={visibleFeatures}
            style={(feature) => {
              const props = feature?.properties || {};
              const rain = Number(props.rainfall ?? props.rainfall_mm ?? 0);
              // Scale from 0 to 400mm
              const ratio = Math.min(rain / 300, 1);
              // Deep blue for high rain, pale blue/white for low
              const r = Math.round(255 - 200 * ratio);
              const g = Math.round(255 - 100 * ratio);
              const b = 255;
              return {
                fillColor: `rgb(${r}, ${g}, ${b})`,
                weight: 0.5,
                opacity: 0.3,
                color: "rgba(255,255,255,0.2)",
                fillOpacity: 0.75
              };
            }}
            onEachFeature={(feature, layer) => {
              const props = feature?.properties || {};
              const village = props.village_name || props.VILLAGE || "Village";
              const rain = Number(props.rainfall ?? props.rainfall_mm ?? 0);
              const recharge = Number(props.effective_recharge ?? 0);
              layer.bindTooltip(`
                <div style="font-family: 'Inter', sans-serif; min-width: 160px; color: #e2e8f0; line-height: 1.5; padding: 4px;">
                  <strong style="color: #fff; font-size: 0.9rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">${village}</strong>
                  <div style="display: flex; flex-direction: column; gap: 2px;">
                    <div><span style="color: #94a3b8; font-weight: 600;">Rainfall:</span> <span style="color: #3b82f6; font-weight: 700;">${rain.toFixed(1)} mm</span></div>
                    <div><span style="color: #94a3b8; font-weight: 600;">Recharge:</span> <span style="color: #10b981; font-weight: 700;">${recharge.toFixed(2)} mm</span></div>
                  </div>
                </div>
              `, { sticky: true, opacity: 0.98 });
            }}
          />
        )}

        {showCanals && surfaceLayers.canals && (
          <GeoJSON
            data={surfaceLayers.canals}
            style={(feature) => surfaceLayerStyle("canals", feature)}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(surfaceLayerTooltip("canals", feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "surface-layer-tooltip"
              });
            }}
          />
        )}

        {showStreams && surfaceLayers.streams && (
          <GeoJSON
            data={surfaceLayers.streams}
            style={(feature) => surfaceLayerStyle("streams", feature)}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(surfaceLayerTooltip("streams", feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "surface-layer-tooltip"
              });
            }}
          />
        )}

        {showDrains && surfaceLayers.drains && (
          <GeoJSON
            data={surfaceLayers.drains}
            style={(feature) => surfaceLayerStyle("drains", feature)}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(surfaceLayerTooltip("drains", feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "surface-layer-tooltip"
              });
            }}
          />
        )}

        {showTanks && surfaceLayers.tanks && (
          <GeoJSON
            data={surfaceLayers.tanks}
            style={(feature) => surfaceLayerStyle("tanks", feature)}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip(surfaceLayerTooltip("tanks", feature), {
                sticky: true,
                direction: "top",
                opacity: 0.96,
                className: "surface-layer-tooltip"
              });
            }}
          />
        )}

        {showDemSurface && surfaceLayers.demContours && (
          <GeoJSON
            data={surfaceLayers.demContours}
            style={(feature) => surfaceLayerStyle("contours", feature)}
            interactive={false}
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
                  matched = (visibleFeatures?.features || []).find((item) => {
                    const itemKey = buildLocationKey(
                      item?.properties?.district,
                      item?.properties?.mandal,
                      item?.properties?.village_name
                    );
                    return itemKey === anomalyKey;
                  });
                }
                if (!matched && Number.isFinite(villageId)) {
                  matched = (visibleFeatures?.features || []).find((item) => Number(item?.properties?.village_id) === villageId);
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

        {showPiezometers && piezometerGeojson && (
          <>
            <GeoJSON
              key={`influence-${selectedDistrictNorm}-${piezometerStations.length}`}
              data={piezometerGeojson}
              pointToLayer={(feature, latlng) => {
                const storage = Number(feature?.properties?.aquifer_storage_factor || 1.0);
                // Radius scales between 2km and 10km based on storage factor
                const dynamicRadius = 2000 + (storage * 8000);
                return L.circle(latlng, {
                  radius: dynamicRadius,
                  color: "#00e5ff",
                  weight: 1.2,
                  dashArray: "4, 8",
                  fillColor: "#00e5ff",
                  fillOpacity: 0.04,
                  className: "influence-zone-circle",
                  interactive: true
                });
              }}
            />
            <GeoJSON
              key={`piezometers-${selectedDistrictNorm}-${piezometerStations.length}`}
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
                  weight: 1.8,
                  fillColor: color,
                  fillOpacity: 0.95,
                  className: "piezometer-sensor-node"
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
          </>
        )}

        {showRechargeZones && rechargeZonesGeojson && (
          <GeoJSON
            key={`recharge-zones-${rechargeZonesGeojson.features.length}`}
            data={rechargeZonesGeojson}
            style={(f) => ({
              color: f.properties.__rechargeColor,
              weight: f.properties.__rechargePriority >= 2 ? 4 : 2,
              fillColor: f.properties.__rechargeColor,
              fillOpacity: 0.18,
              dashArray: f.properties.__rechargePriority === 3 ? "" : "6, 4"
            })}
            onEachFeature={(f, layer) => {
              const m = f.properties.__rechargeMeta || {};
              layer.bindTooltip(`
                <div style="font-family: 'Inter', sans-serif; min-width: 180px; color: #e2e8f0; line-height: 1.5; padding: 4px;">
                  <strong style="color: ${f.properties.__rechargeColor}; font-size: 0.9rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">Recharge Site Selection</strong>
                  <div style="color: #fff; font-weight: 700; margin-bottom: 4px;">${f.properties.__rechargeLabel}</div>
                  
                  <div style="display: flex; flex-direction: column; gap: 3px; font-size: 0.75rem;">
                    <div style="display: flex; justify-content: space-between;">
                      <span style="color: #94a3b8;">Potential:</span>
                      <span style="color: #fff;">${(m.potential * 100).toFixed(0)}%</span>
                    </div>
                    <div style="display: flex; justify-content: space-between;">
                      <span style="color: #94a3b8;">Urgency:</span>
                      <span style="color: #fff;">${(m.urgency * 100).toFixed(0)}%</span>
                    </div>
                    <div style="display: flex; justify-content: space-between;">
                      <span style="color: #94a3b8;">Feasibility:</span>
                      <span style="color: #fff;">${(m.feasibility * 100).toFixed(0)}%</span>
                    </div>
                    <div style="margin-top: 4px; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-between;">
                      <span style="color: #94a3b8; font-weight: 600;">Overall Score:</span>
                      <span style="color: ${f.properties.__rechargeColor}; font-weight: 800;">${(m.score * 100).toFixed(1)}</span>
                    </div>
                  </div>
                  
                  <div style="font-size: 0.65rem; color: #64748b; margin-top: 8px;">Village: ${f.properties.village_name}</div>
                </div>
              `, { sticky: true, className: "recharge-tooltip" });
              layer.on("click", () => onVillageClick(f));
            }}
          />
        )}

        {showWells && wellsData && <WellsLayerController data={wellsData} onVillageClick={onVillageClick} />}

        {(showAquifer || showRecharge) && aquiferGeojson && (
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
              const meta = aquiferTypeMeta(feature);
              const code = props.AQUI_CODE;
              const area = Number(props.area || props.AREA_SQKM);
              
              let body = `<strong>Type:</strong> ${meta.label}<br/>`;
              if (code && code !== "NA") body += `<strong>Code:</strong> ${code}<br/>`;
              if (Number.isFinite(area)) body += `<strong>Area:</strong> ${area.toFixed(2)} km²<br/>`;

              layer.bindTooltip(`
                <div style="font-family: 'Inter', sans-serif; min-width: 160px; padding: 6px; line-height: 1.5;">
                  <strong style="color: #fff; font-size: 0.95rem; display: block; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 4px;">Aquifer Unit</strong>
                  <div style="display: flex; flex-direction: column; gap: 2px;">
                    <div><span style="color: #94a3b8; font-weight: 600;">Lithology:</span> <span style="color: ${meta.color}; font-weight: 700;">${meta.label}</span></div>
                    ${code && code !== "NA" ? `<div><span style="color: #94a3b8; font-weight: 600;">Code:</span> <span style="color: #fff;">${code}</span></div>` : ""}
                    ${Number.isFinite(area) ? `<div><span style="color: #94a3b8; font-weight: 600;">Area:</span> <span style="color: #fff;">${area.toFixed(2)} km²</span></div>` : ""}
                  </div>
                </div>
              `, {
                sticky: true,
                direction: "top",
                opacity: 0.98,
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

        <RegionalLabels filters={filters} />
        <NtrVillageClickFallback
          filteredGeojson={visibleFeatures}
          selectedDistrictNorm={selectedDistrictNorm}
          onVillageClick={onVillageClick}
        />
        <FlyToSelection popupLngLat={popupLngLat} selectedFeature={selectedFeature} filters={filters} />
        <FitToFilterSelection filteredGeojson={visibleFeatures} filters={filters} stateBoundaryLayer={stateBoundaryLayer} />

        <MapLegend
          mapMode={mapMode}
          showGroundwaterLevels={showGroundwaterLevels}
          showPiezometers={showPiezometers}
          showWells={showWells}
          showAnomalies={showAnomalies}
          showRecharge={showRecharge}
          showRechargeZones={showRechargeZones}
          showAquifer={showAquifer}
          showSoil={showSoil}
          showLulc={showLulc}
          showCanals={showCanals}
          showStreams={showStreams}
          showDrains={showDrains}
          showTanks={showTanks}
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
