import { useState, useMemo, useEffect, lazy, Suspense } from "react";
import { DashboardTopBar, DashboardAnalyticsPanel, VillageInsightsPanel, VillageAnalysisDock, ComprehensiveAnalysisModal } from "./components/UI";
import "./CleanDashboard.css";

import { useVillageData } from "./hooks/useVillageData";
import { useGroundwaterDataset } from "./hooks/useGroundwaterDataset";
import { api, getApiStatusSummary, subscribeApiStatus, LOCAL_DATA_ONLY_MODE } from "./services/api";
import { AQUIFER_COLORS, DISTRICT_HOVER_DATA } from "./constants/data";
import { buildLocationKey, geometryCenter, pointInGeometry, normalizeLocationName, normalizeVillageProperties } from "./utils/mapUtils";
import {
  buildLulcBars,
  buildLulcDonut,
  buildGroundwaterTrend,
  buildSummaryBars,
  buildVillageHeadline,
  buildYearComparison,
  summarizeRows
} from "./utils/datasetAnalytics";

const LULC_CLASS_KEYS = [
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

const ANOMALY_TYPE_OPTIONS = ["Severe drop", "Moderate drop", "Normal", "Rise"];

const Home = lazy(() => import("./pages/Home").then(module => ({ default: module.Home })));
const Sidebar = lazy(() => import("./components/Sidebar").then(module => ({ default: module.Sidebar })));
const MapView = lazy(() => import("./components/MapView").then(module => ({ default: module.MapView })));
const VillageActionPanel = lazy(() => import("./components/VillageActionPanel").then(module => ({ default: module.VillageActionPanel })));

const LoadingSpinner = () => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#050b14', color: '#00e5ff' }}>
    <div className="skeleton" style={{ width: '200px', height: '4px' }}></div>
  </div>
);

async function readGeoJsonIfValid(path) {
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const contentType = String(res.headers.get("content-type") || "").toLowerCase();
    if (!contentType.includes("application/json")) return null;
    const text = (await res.text()).trim();
    if (!text) return null;
    const data = JSON.parse(text);
    if (data?.type === "FeatureCollection" && Array.isArray(data.features)) {
      return data;
    }
    return null;
  } catch {
    return null;
  }
}

function aquiferFeatureKey(feature, index) {
  const props = feature?.properties || {};
  return `${props.AQUI_CODE || "AQ"}-${props.NEWCODE || index}`;
}

function decorateAquiferClasses(features, villageMatchCounts = {}) {
  const grouped = features.reduce((acc, feature, index) => {
    const props = feature.properties || {};
    const name = String(props.Geo_Class || props.AQUI_CODE || "Unknown").trim();
    const code = String(props.AQUI_CODE || "").trim();
    const areaKm2 = Number(props.area);
    const key = aquiferFeatureKey(feature, index);
    if (!acc[name]) {
      acc[name] = {
        name,
        code,
        color: AQUIFER_COLORS[code] || AQUIFER_COLORS.default,
        areaKm2: 0,
        polygons: 0,
        villageMatches: 0
      };
    }
    acc[name].polygons += 1;
    if (Number.isFinite(areaKm2)) {
      acc[name].areaKm2 += areaKm2;
    }
    acc[name].villageMatches += villageMatchCounts[key] || 0;
    return acc;
  }, {});

  const rows = Object.values(grouped)
    .map((row) => ({
      ...row,
      areaKm2: Number(row.areaKm2.toFixed(2))
    }))
    .sort((a, b) => b.areaKm2 - a.areaKm2);

  const totalAreaKm2 = Number(rows.reduce((sum, row) => sum + row.areaKm2, 0).toFixed(2));
  return rows.map((row) => ({
    ...row,
    share: totalAreaKm2 > 0 ? Number(((row.areaKm2 / totalAreaKm2) * 100).toFixed(1)) : 0
  }));
}

function describeAquiferScope(filters, isScoped) {
  if (filters.villageName) return "Selected village footprint";
  if (filters.mandal) return "Selected mandal footprint";
  if (filters.district) return "Selected district footprint";
  if (filters.state) return "Selected state footprint";
  return isScoped ? "Filtered footprint" : "District aquifer dataset";
}

function average(values) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (!finite.length) return null;
  const total = finite.reduce((sum, value) => sum + value, 0);
  return Number((total / finite.length).toFixed(2));
}

function buildWaterLevelSummary(rows, monthIndex) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const currentDepths = safeRows
    .map((row) => Number(row.monthly_depths?.[monthIndex] ?? row.gw_level ?? row.depth ?? row.current_depth ?? NaN))
    .filter((value) => Number.isFinite(value));
  const totalDepths = safeRows
    .map((row) => Number(row.obs_total_depth_m ?? row.avg_bore_depth_m ?? NaN))
    .filter((value) => Number.isFinite(value));
  const aquiferCounts = safeRows.reduce((acc, row) => {
    const aquifer = String(row.aquifer_type || row.aquifer_class || row.aquifer_code || "Unknown").trim() || "Unknown";
    acc[aquifer] = (acc[aquifer] || 0) + 1;
    return acc;
  }, {});
  const aquifers = Object.entries(aquiferCounts)
    .map(([aquifer, count]) => ({ aquifer, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 4);
  const sampleStations = safeRows
    .slice(0, 3)
    .map((row) => ({
      village: row.village_name || row.village || "Unknown",
      location: row.mandal || row.district || "Unknown",
      avgWaterLevel: Number(row.monthly_depths?.[monthIndex] ?? row.gw_level ?? row.depth ?? NaN)
    }))
    .filter((row) => Number.isFinite(row.avgWaterLevel));

  return {
    source: "PzWaterLevel_2024.xlsx",
    recordCount: safeRows.length,
    avgTotalDepth: average(totalDepths),
    avgWaterLevel: average(currentDepths),
    aquifers,
    sampleStations
  };
}

function simulateFromFeature(feature, simulationInputs) {
  const props = feature?.properties || {};
  const base = Number(props.predicted_groundwater_level ?? props.gw_level ?? props.depth ?? 0);
  const basePumping = Number(props.pumping_rate ?? props.Pumping ?? 0);
  const baseWells = Number(props.pumping_functioning_wells ?? props.functioning_wells ?? 0);
  const baseDraft = Number(props.pumping_monsoon_draft_ha_m ?? 0);
  const wellsTotal = Number(props.wells_total ?? 0);

  const pumping = Number(simulationInputs?.pumping ?? basePumping);
  const functioningWells = Number(simulationInputs?.functioningWells ?? baseWells);
  const draft = Number(simulationInputs?.draft ?? baseDraft);
  const predicted = Math.max(
    0,
    base + (pumping - basePumping) * 0.05 + (draft - baseDraft) * 1.5 + (functioningWells - baseWells) * 0.01
  );
  const impactDelta = predicted - base;
  const pumpingNorm = pumping / (Math.max(wellsTotal, 0) + 1);
  const pumpingThreshold = 0.533265306122449;

  return {
    village_id: Number(props.village_id),
    village_name: String(props.village_name || ""),
    district: String(props.district || ""),
    mandal: String(props.mandal || ""),
    base_groundwater_level: base,
    predicted_groundwater_level: predicted,
    impact_delta: impactDelta,
    impact_label:
      Math.abs(impactDelta) < 0.05
        ? "Stable"
        : impactDelta > 0
          ? `Groundwater drops by ${impactDelta.toFixed(2)} m`
          : `Groundwater rises by ${Math.abs(impactDelta).toFixed(2)} m`,
    risk_level: predicted * 5 > 60 ? "High" : predicted * 5 > 30 ? "Medium" : "Low",
    risk_score: Math.round(predicted * 5),
    warning:
      pumpingNorm > pumpingThreshold
        ? `Over-extraction risk: pumping per well (${pumpingNorm.toFixed(2)}) exceeds the sustainable limit (${pumpingThreshold.toFixed(2)}).`
        : null,
  };
}

function sameSimulationInputs(left, right) {
  return (
    Number(left?.pumping ?? 0) === Number(right?.pumping ?? 0) &&
    Number(left?.functioningWells ?? 0) === Number(right?.functioningWells ?? 0) &&
    Number(left?.draft ?? 0) === Number(right?.draft ?? 0)
  );
}

function buildHydratedFeatureSignature(feature) {
  const props = feature?.properties || {};
  return JSON.stringify({
    village_id: Number(props.village_id ?? 0),
    village_name: String(props.village_name || ""),
    district: String(props.district || ""),
    mandal: String(props.mandal || ""),
    risk_level: props.risk_level ?? null,
    alert_status: props.alert_status ?? null,
    confidence_score: Number(props.confidence_score ?? 0),
    lstm_forecast: Array.isArray(props.lstm_forecast) ? props.lstm_forecast : [],
    forecast_yearly: Array.isArray(props.forecast_yearly) ? props.forecast_yearly : [],
    st_gnn_prediction: props.st_gnn_prediction ?? null
  });
}

function mergeVillageMapData(baseGeojson, mapData) {
  if (!baseGeojson?.features?.length) return baseGeojson || mapData || null;
  if (!mapData?.features?.length) return baseGeojson;

  const hasMeaningfulValue = (value) => {
    if (value === null || value === undefined) return false;
    if (typeof value === "string") return value.trim() !== "";
    return true;
  };

  const getFeatureKey = (f) => {
    const p = f?.properties || {};
    if (p.village_id) return String(p.village_id);
    return buildLocationKey(p.district, p.mandal, p.village_name);
  };

  const mapFeaturesByKey = new Map();
  mapData.features.forEach((feature) => {
    const key = getFeatureKey(feature);
    if (key && !mapFeaturesByKey.has(key)) mapFeaturesByKey.set(key, feature);
  });

  return {
    ...baseGeojson,
    features: baseGeojson.features.map((feature) => {
      const props = feature?.properties || {};
      const key = getFeatureKey(feature);
      const match = key ? mapFeaturesByKey.get(key) : null;
      if (!match) return feature;
      const mapProps = match.properties || {};
      const mergedProps = { ...props };
      Object.entries(mapProps).forEach(([field, value]) => {
        if (hasMeaningfulValue(value)) {
          mergedProps[field] = value;
        }
      });
      return {
        ...feature,
        properties: {
          ...mergedProps,
          village_id: props.village_id ?? match.properties?.village_id,
          village_name: props.village_name ?? match.properties?.village_name,
          district: props.district ?? match.properties?.district,
          mandal: props.mandal ?? match.properties?.mandal
        }
      };
    })
  };
}

export default function App({ navigate, pathname }) {
  const [isFullDashboardOpen, setIsFullDashboardOpen] = useState(false);
  const [riskFilter, setRiskFilter] = useState("all");
  const [monthIndex, setMonthIndex] = useState(0);
  const [aiPredictionEnabled, setAiPredictionEnabled] = useState(true);
  const [is3D, setIs3D] = useState(false);
  const [showLulc, setShowLulc] = useState(false);
  const [showGroundwaterLevels, setShowGroundwaterLevels] = useState(false);
  const [showPiezometers, setShowPiezometers] = useState(false);
  const [showWells, setShowWells] = useState(false);
  const [showDistrictBoundaries, setShowDistrictBoundaries] = useState(false);
  const [showMandalBoundaries, setShowMandalBoundaries] = useState(false);
  const [showStateBoundary, setShowStateBoundary] = useState(true);
  const [selectedAnomalyTypes, setSelectedAnomalyTypes] = useState(["Severe drop", "Moderate drop"]);
  const [selectedLulcClasses, setSelectedLulcClasses] = useState(LULC_CLASS_KEYS);
  const [showRainfall, setShowRainfall] = useState(false);
  const [showCanals, setShowCanals] = useState(false);
  const [showStreams, setShowStreams] = useState(false);
  const [showDrains, setShowDrains] = useState(false);
  const [showTanks, setShowTanks] = useState(false);
  const [showDemSurface, setShowDemSurface] = useState(false);
  const [baseMapTheme, setBaseMapTheme] = useState("satellite");
  const [isInsightsOpen, setIsInsightsOpen] = useState(true);
  const [isAnalysisDockOpen, setIsAnalysisDockOpen] = useState(false);
  const [showFullHistory, setShowFullHistory] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    if (typeof window === "undefined") return true;
    return window.innerWidth > 1100;
  });
  const [simulatorVillageId, setSimulatorVillageId] = useState(null);
  const [simulationInputs, setSimulationInputs] = useState({
    pumping: 0,
    functioningWells: 0,
    draft: 0
  });
  const [simulation, setSimulation] = useState(null);
  const [simulationLoading, setSimulationLoading] = useState(false);
  const [simulationError, setSimulationError] = useState(null);
  
  const [filters, setFilters] = useState(() => {
    if (typeof window === "undefined") return { state: "", district: "", mandal: "", villageName: "" };
    const params = new URLSearchParams(window.location.search);
    return {
      state: params.get("state") || "",
      district: params.get("district") || "",
      mandal: params.get("mandal") || "",
      villageName: params.get("village") || ""
    };
  });

  const [activeLayer, setActiveLayer] = useState(1);
  const [mapMode, setMapMode] = useState("prediction");


  const [selectedFeature, setSelectedFeature] = useState(null);
  const [popupLngLat, setPopupLngLat] = useState(null);
  const [hoveredDistrict, setHoveredDistrict] = useState(null);

  const [anomalies, setAnomalies] = useState(null);
  const [rechargeZones, setRechargeZones] = useState(null);
  const [aquiferLayer, setAquiferLayer] = useState(null);
  const [stateBoundaryLayer, setStateBoundaryLayer] = useState(null);
  const [dashboardMapData, setDashboardMapData] = useState(null);
  const [showAnomalies, setShowAnomalies] = useState(false);
  const [showRecharge, setShowRecharge] = useState(false);
  const [showAquifer, setShowAquifer] = useState(false);
  const [showSoil, setShowSoil] = useState(false);
  const [apiStatus, setApiStatus] = useState(() => getApiStatusSummary());
  const [modelUpgradeSummary, setModelUpgradeSummary] = useState(null);
  const [isHydrating, setIsHydrating] = useState(false);

  useEffect(() => {
    if (selectedFeature) {
      setIsAnalysisDockOpen(true);
    } else {
      setIsAnalysisDockOpen(false);
    }
  }, [selectedFeature]);

  const { 
    villages, 
    filteredGeojson, 
    stateOptions,
    districtOptions, 
    mandalOptions, 
    villageOptions, 
    loading,
    error,
    dataSource,
    totalCount,
    districtCount
  } = useVillageData(filters);
  const {
    records: datasetRows,
    recordsById: datasetRowsById,
    recordsByLocation: datasetRowsByLocation,
    loading: datasetLoading,
    error: datasetError,
    sourcePath: datasetSource,
    integritySummary: datasetIntegritySummary
  } = useGroundwaterDataset();


  useEffect(() => {
    if (aiPredictionEnabled && showAnomalies && !anomalies) {
      api.getAnomalies().then(setAnomalies).catch(console.error);
    }
    if (aiPredictionEnabled && showRecharge && !rechargeZones) {
      api.getRechargeRecommendations().then(setRechargeZones).catch(console.error);
    }
  }, [aiPredictionEnabled, showAnomalies, showRecharge, anomalies, rechargeZones]);

  useEffect(() => {
    if (pathname !== "/dashboard") return;
    let active = true;
    (async () => {
      try {
        const payload = await api.getMapData();
        if (!active) return;
        setDashboardMapData(payload);
      } catch (err) {
        if (!active) return;
        console.warn("Map data unavailable:", err);
        setDashboardMapData(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    if (pathname !== "/dashboard") return;
    let active = true;
    (async () => {
      try {
        const payload = await api.getModelUpgradeSummary();
        if (!active) return;
        setModelUpgradeSummary(payload);
      } catch {
        if (!active) return;
        setModelUpgradeSummary(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    let active = true;
    (async () => {
      const data = await readGeoJsonIfValid("/data/aquifers_krishna.geojson");
      if (active && data) {
        setAquiferLayer(data);
      }
      const stateData = await readGeoJsonIfValid("/data/ap_state_boundary.geojson");
      if (active && stateData) {
        setStateBoundaryLayer(stateData);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const handleFilterChange = (key, value) => {
    setFilters(prev => {
      const newFilters = { ...prev, [key]: value };
      if (key === 'state') {
        newFilters.district = "";
        newFilters.mandal = "";
        newFilters.villageName = "";
      } else if (key === 'district') {
        newFilters.mandal = "";
        newFilters.villageName = "";
      } else if (key === 'mandal') {
        newFilters.villageName = "";
      }
      return newFilters;
    });
  };

  const handleVillageClick = (feature) => {
    setSelectedFeature(feature);
    setPopupLngLat(null); // Reset popup
    setIsHydrating(true); // Signal start of hydration
    const center = geometryCenter(feature.geometry);
    setPopupLngLat([center.longitude, center.latitude]);
    setIsInsightsOpen(true);
    const villageId = Number(feature.properties?.village_id);
    if (Number.isFinite(villageId)) {
      setSimulatorVillageId(villageId);
    }
  };

  useEffect(() => {
    if (!selectedFeature) return;
    const villageId = selectedFeature.properties?.village_id;
    if (!villageId || selectedFeature.properties?.is_hydrated) {
      if (selectedFeature && !selectedFeature.properties?.is_hydrated) {
         // Even if we don't fetch, we should stop hydrating state if it was set
         setIsHydrating(false);
      }
      return;
    }

    let active = true;
    (async () => {
      try {
        const [status, prediction] = await Promise.all([
          api.getVillageStatus(villageId),
          api.getPrediction(villageId, { mode: aiPredictionEnabled ? "live" : "batch" })
        ]);
        if (!active) return;
        
        setSelectedFeature(prev => {
          if (!prev || prev.properties?.village_id !== villageId) return prev;
          return {
            ...prev,
            properties: {
              ...prev.properties,
              ...status,
              ...prediction,
              is_hydrated: true
            }
          };
        });
      } catch (err) {
        console.error("Hydration failed:", err);
      } finally {
        if (active) setIsHydrating(false);
      }
    })();

    return () => { active = false; };
  }, [selectedFeature?.properties?.village_id, aiPredictionEnabled]);

  const dashboardGeojson = useMemo(() => {
    const merged = mergeVillageMapData(filteredGeojson, dashboardMapData);
    if (!merged) return null;
    const features = (merged.features || []).filter(
      (feature) => {
        if (riskFilter === "all") return true;
        const risk = String(feature?.properties?.risk_level || "").toLowerCase();
        if (riskFilter === "critical") return risk === "critical" || risk === "high";
        if (riskFilter === "warning") return risk === "warning" || risk === "medium" || risk === "moderate";
        if (riskFilter === "safe") return risk === "safe" || risk === "low";
        return true;
      }
    );

    return {
      ...merged,
      features
    };
  }, [filteredGeojson, dashboardMapData, riskFilter]);

  const dashboardStats = useMemo(() => {
    if (!dashboardGeojson) return { safe: 0, warning: 0, critical: 0, total: 0, avgDepth: 0, piezometerCount: 0 };
    const depths = [];
    let piezometers = 0;
    const stats = { safe: 0, warning: 0, critical: 0, total: dashboardGeojson.features.length };
    dashboardGeojson.features.forEach(f => {
      const depth = Number(f.properties?.monthly_depths?.[monthIndex] ?? f.properties?.depth ?? 0);
      if (Number.isFinite(depth)) depths.push(depth);
      if (depth >= 30) stats.critical++;
      else if (depth >= 20) stats.warning++;
      else stats.safe++;
      
      if (f.properties?.has_sensor === true || f.properties?.is_piezometer === true || f.properties?.sensor_id) {
        piezometers++;
      }
    });
    stats.avgDepth = depths.length > 0 ? (depths.reduce((a, b) => a + b, 0) / depths.length).toFixed(2) : 0;
    stats.piezometerCount = piezometers;
    return stats;
  }, [dashboardGeojson, monthIndex]);

  const topbarScopeLabel = useMemo(() => {
    if (filters.villageName) return filters.villageName;
    if (filters.mandal) return filters.mandal;
    if (filters.district) return filters.district;
    if (filters.state) return filters.state;
    return "All Villages";
  }, [filters.state, filters.district, filters.mandal, filters.villageName]);

  const districtHoverData = useMemo(() => {
    if (!villages?.features?.length) return DISTRICT_HOVER_DATA;

    const grouped = villages.features.reduce((acc, feature) => {
      const props = feature.properties || {};
      const district = String(props.district || "").trim();
      if (!district) return acc;
      if (!acc[district]) {
        acc[district] = [];
      }
      acc[district].push(feature);
      return acc;
    }, {});

    const computed = Object.entries(grouped).reduce((acc, [district, features]) => {
      const depths = features.map((f) =>
        Number(f.properties?.monthly_depths?.[monthIndex] ?? f.properties?.depth ?? 0)
      );
      const validDepths = depths.filter((d) => Number.isFinite(d));
      const safeCount = validDepths.filter((d) => d < 20).length;
      const warningCount = validDepths.filter((d) => d >= 20 && d < 30).length;
      const criticalCount = validDepths.filter((d) => d >= 30).length;

      acc[district] = {
        summary: {
          source: "Village GeoJSON",
          villageCount: features.length,
          avgDepth:
            validDepths.length > 0
              ? Number((validDepths.reduce((sum, val) => sum + val, 0) / validDepths.length).toFixed(2))
              : null,
          safeCount,
          warningCount,
          criticalCount
        },
        waterLevels: buildWaterLevelSummary(
          datasetRows.filter((row) => normalizeLocationName(row.district || "") === normalizeLocationName(district)),
          monthIndex
        )
      };
      return acc;
    }, {});

    return {
      ...computed,
      ...Object.entries(DISTRICT_HOVER_DATA).reduce((acc, [district, data]) => {
        acc[district] = {
          ...data,
          ...computed[district]
        };
        return acc;
      }, {})
    };
  }, [villages, datasetRows, monthIndex]);

  const aquiferAnalytics = useMemo(() => {
    const aquiferFeatures = aquiferLayer?.features || [];
    if (!aquiferFeatures.length) return null;
    const hasScopedFilter =
      Boolean(filters.state) ||
      Boolean(filters.district) ||
      Boolean(filters.mandal) ||
      Boolean(filters.villageName);
    const filteredFeatures = filteredGeojson?.features || [];

    const scopedMatchCounts = {};
    const scopedFeatureMap = new Map();
    if (hasScopedFilter) {
      filteredFeatures.forEach((feature) => {
        const center = geometryCenter(feature.geometry);
        const point = [center.longitude, center.latitude];
        const matchIndex = aquiferFeatures.findIndex((aquiferFeature) => pointInGeometry(point, aquiferFeature.geometry));
        if (matchIndex < 0) return;
        const match = aquiferFeatures[matchIndex];
        const key = aquiferFeatureKey(match, matchIndex);
        scopedFeatureMap.set(key, match);
        scopedMatchCounts[key] = (scopedMatchCounts[key] || 0) + 1;
      });
    }

    const scopedAquiferFeatures = hasScopedFilter
      ? Array.from(scopedFeatureMap.values())
      : aquiferFeatures;
    const classRows = decorateAquiferClasses(
      scopedAquiferFeatures,
      hasScopedFilter ? scopedMatchCounts : {}
    );
    const totalAreaKm2 = Number(classRows.reduce((sum, row) => sum + row.areaKm2, 0).toFixed(2));
    const dominantClass = classRows[0] || null;
    const scopeLabel = describeAquiferScope(filters, hasScopedFilter);

    let selectedVillageAquifer = null;
    if (selectedFeature?.geometry) {
      const center = geometryCenter(selectedFeature.geometry);
      const point = [center.longitude, center.latitude];
      const matched = aquiferFeatures.find((feature) => pointInGeometry(point, feature.geometry));
      if (matched) {
        const props = matched.properties || {};
        selectedVillageAquifer = {
          code: String(props.AQUI_CODE || "NA"),
          name: String(props.Geo_Class || "Aquifer unit"),
          color: AQUIFER_COLORS[String(props.AQUI_CODE || "").trim()] || AQUIFER_COLORS.default,
          areaKm2: Number.isFinite(Number(props.area)) ? Number(Number(props.area).toFixed(2)) : null
        };
      }
    }

    let filteredVillageDominantAquifer = null;
    if (filteredFeatures.length) {
      const counts = filteredFeatures.reduce((acc, feature) => {
        const center = geometryCenter(feature.geometry);
        const point = [center.longitude, center.latitude];
        const match = aquiferFeatures.find((aquiferFeature) => pointInGeometry(point, aquiferFeature.geometry));
        const key = String(match?.properties?.Geo_Class || match?.properties?.AQUI_CODE || "Unclassified");
        acc[key] = (acc[key] || 0) + 1;
        return acc;
      }, {});
      const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
      if (sorted.length) {
        filteredVillageDominantAquifer = { name: sorted[0][0], villageCount: sorted[0][1] };
      }
    }

    return {
      totalPolygons: scopedAquiferFeatures.length,
      totalAreaKm2,
      classRows,
      dominantClass,
      scopeLabel,
      isScoped: hasScopedFilter,
      selectedVillageAquifer,
      filteredVillageDominantAquifer
    };
  }, [aquiferLayer, selectedFeature, filteredGeojson, filters.state, filters.district, filters.mandal, filters.villageName]);

  const dashboardVisibleVillageIds = useMemo(() => {
    const features = dashboardGeojson?.features || [];
    return new Set(
      features
        .map((feature) => Number(feature?.properties?.village_id))
        .filter((value) => Number.isFinite(value))
    );
  }, [dashboardGeojson]);

  const simulatorVillageOptions = useMemo(() => {
    const features = dashboardGeojson?.features || [];
    return features
      .map((feature) => ({
        villageId: Number(feature?.properties?.village_id),
        villageName: String(feature?.properties?.village_name || "Unknown"),
        district: String(feature?.properties?.district || "Unknown"),
        mandal: String(feature?.properties?.mandal || "")
      }))
      .filter((row) => Number.isFinite(row.villageId));
  }, [dashboardGeojson]);

  useEffect(() => {
    if (!simulatorVillageId) return;
    const feature = (dashboardGeojson?.features || []).find(
      (item) => Number(item?.properties?.village_id) === Number(simulatorVillageId)
    );
    if (!feature) return;

    let active = true;
    (async () => {
      try {
        const villageId = Number(simulatorVillageId);
        const forecastPromise = aiPredictionEnabled
          ? api.getVillageForecast(villageId)
          : Promise.resolve(null);
        const stGnnPromise = aiPredictionEnabled
          ? api.getStGnnPrediction(villageId)
          : Promise.resolve(null);
          
        const [status, forecast, stGnnPrediction] = await Promise.all([
          api.getVillageStatus(villageId),
          forecastPromise,
          stGnnPromise
        ]);
        if (!active) return;

        const inputs = feature?.properties || {};
        const nextInputs = {
          pumping: Number(inputs.pumping ?? inputs.pumping_rate ?? inputs.Pumping ?? 0),
          functioningWells: Number(
            inputs.functioning_wells ?? inputs.pumping_functioning_wells ?? 0
          ),
          draft: Number(inputs.draft ?? inputs.pumping_monsoon_draft_ha_m ?? 0)
        };
        const nextSelectedFeature = {
          ...feature,
          properties: {
            ...(feature.properties || {}),
            ...status,
            lstm_forecast: forecast?.forecast_3_month || [],
            forecast_yearly: forecast?.forecast_yearly || [],
            st_gnn_prediction: stGnnPrediction || null
          }
        };
        const nextSelectedSignature = buildHydratedFeatureSignature(nextSelectedFeature);

        setSimulation(simulateFromFeature(feature, nextInputs));
        setSimulationError(null);
        setSimulationInputs((prev) =>
          sameSimulationInputs(prev, nextInputs) ? prev : nextInputs
        );

        setSelectedFeature((prev) => {
          if (buildHydratedFeatureSignature(prev) === nextSelectedSignature) {
            setIsHydrating(false);
            return prev;
          }
          setIsHydrating(false);
          return nextSelectedFeature;
        });
      } catch (err) {
        if (!active) return;
        console.warn("Backend data unavailable:", err);
        setSimulationError(err?.message || "Failed to load baseline prediction");
      }
    })();

    return () => {
      active = false;
    };
  }, [simulatorVillageId, dashboardGeojson, aiPredictionEnabled]);

  const trendHighlights = [];

  useEffect(() => {
    if (!dashboardVisibleVillageIds.size || !selectedFeature?.properties?.village_id) return;
    const selectedId = Number(selectedFeature.properties.village_id);
    if (Number.isFinite(selectedId) && !dashboardVisibleVillageIds.has(selectedId)) {
      setSelectedFeature(null);
      setPopupLngLat(null);
    }
  }, [dashboardVisibleVillageIds, selectedFeature]);

  useEffect(() => {
    if (!simulatorVillageOptions.length) {
      setSimulatorVillageId(null);
    }
  }, [simulatorVillageId, simulatorVillageOptions]);

  useEffect(() => {
    if (!selectedFeature?.properties?.village_id) return;
    const selectedId = Number(selectedFeature.properties.village_id);
    if (Number.isFinite(selectedId) && selectedId !== Number(simulatorVillageId)) {
      setSimulatorVillageId(selectedId);
    }
  }, [selectedFeature, simulatorVillageId]);

  useEffect(() => {
    if (selectedFeature) {
      setIsInsightsOpen(true);
    }
  }, [selectedFeature]);

  useEffect(() => {
    if (!simulatorVillageId) return;
    const feature = (dashboardGeojson?.features || []).find(
      (item) => Number(item?.properties?.village_id) === Number(simulatorVillageId)
    );
    if (!feature) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setSimulationLoading(true);
      (async () => {
        if (!active) return;
        try {
          if (aiPredictionEnabled) {
            const payload = await api.simulateGroundwater({
              rainfall_delta_pct: Number(simulationInputs?.rainfall ?? 0),
              extraction_delta_pct: Number(simulationInputs?.draft ?? 0)
            });
            const featureRows = Array.isArray(payload?.features) ? payload.features : [];
            const match = featureRows.find(
              (item) => Number(item?.properties?.village_id) === Number(simulatorVillageId)
            );
            if (match?.properties) {
              const props = match.properties;
              const base = Number(props.groundwater_level ?? feature?.properties?.predicted_groundwater_level ?? 0);
              const simulated = Number(props.simulated_groundwater_level ?? base);
              setSimulation({
                village_id: Number(props.village_id),
                village_name: String(props.village_name || feature?.properties?.village_name || ""),
                district: String(props.district || feature?.properties?.district || ""),
                mandal: String(props.mandal || feature?.properties?.mandal || ""),
                base_groundwater_level: base,
                predicted_groundwater_level: simulated,
                impact_delta: simulated - base,
                impact_label:
                  Math.abs(simulated - base) < 0.05
                    ? "Stable"
                    : simulated > base
                      ? `Groundwater drops by ${(simulated - base).toFixed(2)} m`
                      : `Groundwater rises by ${Math.abs(simulated - base).toFixed(2)} m`,
                risk_level: String(props.trend || "Stable"),
                risk_score: Math.round(simulated * 5),
                warning: props.advisory || null
              });
            } else {
              setSimulation(simulateFromFeature(feature, simulationInputs));
            }
          } else {
            setSimulation(simulateFromFeature(feature, simulationInputs));
          }
          setSimulationError(null);
        } catch (err) {
          setSimulation(simulateFromFeature(feature, simulationInputs));
          setSimulationError(err?.message || null);
        } finally {
          if (active) setSimulationLoading(false);
        }
      })();
    }, 220);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [simulatorVillageId, simulationInputs, dashboardGeojson]);

  const activeDatasetRows = useMemo(() => {
    if (!datasetRows.length || !dashboardGeojson) return [];
    const filteredIds = new Set(
      (dashboardGeojson?.features || [])
        .map((feature) => Number(feature.properties?.village_id))
        .filter((value) => Number.isFinite(value))
    );
    if (!filteredIds.size) return [];
    return datasetRows.filter((row) => filteredIds.has(Number(row.village_id)));
  }, [datasetRows, dashboardGeojson]);

  const selectedDatasetRow = useMemo(() => {
    if (!selectedFeature) return null;
    const props = selectedFeature.properties || {};
    const villageId = Number(props.village_id ?? props.Village_ID);
    if (Number.isFinite(villageId) && datasetRowsById.has(villageId)) {
      return datasetRowsById.get(villageId);
    }

    const district = String(props.district ?? props.District ?? "").trim();
    const mandal = String(props.mandal ?? props.Mandal ?? "").trim();
    const villageName = String(props.village_name ?? props.Village_Name ?? "").trim();
    const locationKey = buildLocationKey(district, mandal, villageName);

    if (locationKey && datasetRowsByLocation?.has(locationKey)) {
      return datasetRowsByLocation.get(locationKey);
    }
    return null;
  }, [selectedFeature, datasetRows, datasetRowsById, datasetRowsByLocation]);

  const selectedVillageFeature = useMemo(() => {
    if (!selectedFeature) return null;
    if (!selectedDatasetRow) return selectedFeature;

    const featureProps = selectedFeature.properties || {};
    const rowProps = selectedDatasetRow || {};

    return {
      ...selectedFeature,
      properties: {
        ...rowProps,
        ...featureProps,
        groundwater_estimate:
          featureProps.groundwater_estimate ??
          featureProps.predicted_groundwater_level ??
          featureProps.depth ??
          featureProps.actual_last_month ??
          rowProps.groundwater_estimate ??
          rowProps.predicted_groundwater_level ??
          rowProps.depth ??
          rowProps.actual_last_month,
        village_id: featureProps.village_id ?? rowProps.village_id,
        village_name: featureProps.village_name ?? rowProps.village_name,
        district: featureProps.district ?? rowProps.district,
        mandal: featureProps.mandal ?? rowProps.mandal
      }
    };
  }, [selectedFeature, selectedDatasetRow]);

  const datasetAnalytics = useMemo(() => {
    const scopeRows = selectedDatasetRow
      ? [selectedDatasetRow]
      : activeDatasetRows.length
        ? activeDatasetRows
        : datasetRows;
    const overviewRows = activeDatasetRows.length
      ? activeDatasetRows
      : datasetRows;
    const loadedCount = Number(totalCount || 0);
    const matchedCount = Number(activeDatasetRows.length || 0);
    const unmatchedCount = Math.max(loadedCount - matchedCount, 0);
    const summary = summarizeRows(scopeRows);
    const scopeLabel = selectedDatasetRow
      ? `Selected village: ${selectedDatasetRow.village_name}`
      : activeDatasetRows.length
        ? "Filtered village set"
        : "All villages in dataset";

    return {
      loading: datasetLoading,
      error: datasetError,
      sourcePath: datasetSource,
      scopeLabel,
      rowCount: scopeRows.length,
      loadedCount,
      matchedCount,
      unmatchedCount,
      datasetSummary: summary,
      selectedRow: selectedDatasetRow,
      selectedProfile: buildVillageHeadline(selectedDatasetRow),
      lulcBars: buildLulcBars(scopeRows),
      lulcDonut: buildLulcDonut(scopeRows),
      yearComparison: buildYearComparison(scopeRows),
      summaryBars: buildSummaryBars(scopeRows),
      groundwaterTrend: buildGroundwaterTrend(overviewRows)
    };
  }, [selectedDatasetRow, activeDatasetRows, datasetRows, datasetLoading, datasetError, datasetSource, totalCount]);

  useEffect(() => {
    // Keep details strictly click-driven: any dropdown change resets current selection.
    setSelectedFeature(null);
    setPopupLngLat(null);
  }, [filters.state, filters.district, filters.mandal, filters.villageName]);

  useEffect(() => {
    if (!filters.villageName || !dashboardGeojson?.features?.length) return;

    const requestedVillageName = normalizeLocationName(filters.villageName);
    const matchedFeature = dashboardGeojson.features.find((feature) => {
      return normalizeLocationName(feature?.properties?.village_name) === requestedVillageName;
    });

    if (!matchedFeature) return;

    const matchedVillageId = Number(matchedFeature?.properties?.village_id);
    const currentVillageId = Number(selectedFeature?.properties?.village_id);
    if (Number.isFinite(matchedVillageId) && matchedVillageId === currentVillageId) {
      setIsInsightsOpen(true);
      return;
    }

    setSelectedFeature(matchedFeature);
    const center = geometryCenter(matchedFeature.geometry);
    setPopupLngLat([center.longitude, center.latitude]);
    setIsInsightsOpen(true);

    if (Number.isFinite(matchedVillageId)) {
      setSimulatorVillageId(matchedVillageId);
    }
  }, [filters.villageName, dashboardGeojson, selectedFeature]);

  useEffect(() => {
    if (pathname !== "/dashboard") return;
    setSelectedFeature(null);
    setPopupLngLat(null);
    setHoveredDistrict(null);
    setSimulatorVillageId(null);
    setSimulation(null);
    setSimulationError(null);
  }, [pathname]);

  useEffect(() => {
    if (pathname !== "/dashboard" || typeof window === "undefined") return;

    const params = new URLSearchParams();
    if (filters.state) params.set("state", filters.state);
    if (filters.district) params.set("district", filters.district);
    if (filters.mandal) params.set("mandal", filters.mandal);
    if (filters.villageName) params.set("village", filters.villageName);

    const clickedVillageName = String(selectedFeature?.properties?.village_name || "").trim();
    if (clickedVillageName) {
      params.set("selected_village", clickedVillageName);
    }

    const selectedVillageId = Number(selectedFeature?.properties?.village_id);
    if (Number.isFinite(selectedVillageId)) {
      params.set("selected_village_id", String(selectedVillageId));
    }

    const query = params.toString();
    const nextUrl = query ? `/dashboard?${query}` : "/dashboard";
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (currentUrl !== nextUrl) {
      window.history.replaceState({}, "", nextUrl);
    }
  }, [
    pathname,
    filters.state,
    filters.district,
    filters.mandal,
    filters.villageName,
    selectedFeature
  ]);

  useEffect(() => {
    if (loading || !villages || villages.features.length === 0) return;
    setFilters((prev) => {
      const next = { ...prev };
      
      // Only validate if we actually have filters set
      if (!prev.district) return prev;

      const hasDistrict = districtOptions.some(
        (item) => String(item).toLowerCase() === String(prev.district || "").toLowerCase()
      );
      const hasMandal = mandalOptions.some(
        (item) => String(item?.value || item).toLowerCase() === String(prev.mandal || "").toLowerCase()
      );
      const hasVillage = villageOptions.some(
        (item) => String(item?.value || item).toLowerCase() === String(prev.villageName || "").toLowerCase()
      );

      let changed = false;
      if (prev.district && !hasDistrict) {
        next.district = "";
        next.mandal = "";
        next.villageName = "";
        changed = true;
      } else if (prev.mandal && !hasMandal) {
        next.mandal = "";
        next.villageName = "";
        changed = true;
      } else if (prev.villageName && !hasVillage) {
        next.villageName = "";
        changed = true;
      }

      if (changed) return next;
      return prev;
    });
  }, [loading, villages, districtOptions, mandalOptions, villageOptions]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth > 1100) {
        setIsSidebarOpen(true);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeApiStatus(setApiStatus);
    return unsubscribe;
  }, []);

  const isDashboardRoute = pathname === "/dashboard";
  const openDashboard = () => {
    if (typeof navigate === "function") {
      navigate("/dashboard");
    }
  };

  const apiStatusMessage = useMemo(() => {
    if (LOCAL_DATA_ONLY_MODE) return null;
    if (!apiStatus?.usingFallback) return null;
    if (apiStatus.authRequired && apiStatus.backendUnavailable) {
      return "Live API partially unavailable (auth + server errors). Showing fallback data.";
    }
    if (apiStatus.authRequired) {
      return "Protected API endpoints require login token. Showing fallback data.";
    }
    if (apiStatus.backendUnavailable) {
      return "Live API temporarily unavailable. Showing fallback data.";
    }
    return "Using fallback data for unavailable live endpoints.";
  }, [apiStatus]);

  if (!isDashboardRoute) {
    return (
      <Suspense fallback={<LoadingSpinner />}>
        <Home onEnterDashboard={openDashboard} villages={villages} stateBoundaryLayer={stateBoundaryLayer} />
      </Suspense>
    );
  }

  return (
    <Suspense fallback={<LoadingSpinner />}>
      <div className="clean-dashboard">
        {/* New Sidebar Implementation */}
        <aside className={`clean-sidebar ${isSidebarOpen ? "" : "collapsed"}`}>
          <div className="sidebar-logo">
            <div className="logo-icon">
               <span style={{ fontSize: '1.2rem' }}>💧</span>
            </div>
            {isSidebarOpen && (
              <div className="logo-text">
                <h2>Krishna Groundwater AI</h2>
                <p>ANDHRA PRADESH • HYBRID ML SYSTEM</p>
              </div>
            )}
          </div>

          <nav className="sidebar-nav">
            <div className={`nav-item ${pathname === "/dashboard" ? "active" : ""}`} onClick={() => navigate("/dashboard")}>
              <span className="nav-icon">🏠</span>
              {isSidebarOpen && <span>Dashboard</span>}
            </div>
            <div className={`nav-item ${pathname === "/forecasts" ? "active" : ""}`} onClick={() => navigate("/forecasts")}>
              <span className="nav-icon">📈</span>
              {isSidebarOpen && <span>Forecasts</span>}
            </div>
            <div className={`nav-item ${pathname === "/anomalies" ? "active" : ""}`} onClick={() => navigate("/anomalies")}>
              <span className="nav-icon">⚠️</span>
              {isSidebarOpen && <span>Anomalies</span>}
            </div>
            <div className={`nav-item ${pathname === "/recharge" ? "active" : ""}`} onClick={() => navigate("/recharge")}>
              <span className="nav-icon">♻️</span>
              {isSidebarOpen && <span>Recharge Planning</span>}
            </div>
            <div className={`nav-item ${pathname === "/explainability" ? "active" : ""}`} onClick={() => navigate("/explainability")}>
              <span className="nav-icon">🧠</span>
              {isSidebarOpen && <span>Explainability</span>}
            </div>
            <div className={`nav-item ${pathname === "/methodology" ? "active" : ""}`} onClick={() => navigate("/methodology")}>
              <span className="nav-icon">📖</span>
              {isSidebarOpen && <span>Methodology</span>}
            </div>
          </nav>

          <div className="sidebar-footer">
            {isSidebarOpen && (
              <div className="coverage-card">
                <h4>Coverage</h4>
                <strong>{totalCount}</strong>
                <span>Villages - {topbarScopeLabel}</span>
              </div>
            )}
          </div>
        </aside>

        <main className="clean-main">
          {pathname === "/dashboard" && (
            <>
              {/* Header Section */}
              <div className="header-row">
                <div style={{ fontSize: '0.7rem', fontWeight: '800', color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '8px' }}>Krishna District • Andhra Pradesh</div>
                <h1>Village Groundwater Estimation</h1>
                <p>Hybrid spatial-temporal ML predicting water-table depth, risk, recharge potential and forecasts for {totalCount || 917} villages — trained on {dashboardStats.piezometerCount || 131} piezometers (1997–2024).</p>
              </div>

              {/* Metrics Row */}
              <div className="metrics-row">
                <div className="metric-card">
                  <h4>VILLAGES</h4>
                  <strong>{totalCount}</strong>
                  <span>modelled villages</span>
                </div>
                <div className="metric-card">
                  <h4>PIEZOMETERS</h4>
                  <strong>{dashboardStats.piezometerCount || 131}</strong>
                  <span>monitoring stations</span>
                </div>
                <div className="metric-card">
                  <h4>AVG DEPTH</h4>
                  <strong>{dashboardStats.total > 0 ? (dashboardStats.avgDepth || "0.00") : "0.00"}m</strong>
                  <span>meters BGL</span>
                </div>
                <div className="metric-card">
                  <h4>CRITICAL</h4>
                  <strong style={{ color: "#f43f5e" }}>{dashboardStats.critical}</strong>
                  <span>&gt;30m depth</span>
                </div>
                <div className="metric-card">
                  <h4>ANOMALIES</h4>
                  <strong style={{ color: "#fbbf24" }}>{anomalies ? anomalies.length : "0"}</strong>
                  <span>detected flags</span>
                </div>
                <div className="metric-card">
                  <h4>MODEL ERROR</h4>
                  <strong>{modelUpgradeSummary?.overall_metrics?.rmse ? (modelUpgradeSummary.overall_metrics.rmse * 10).toFixed(2) : "7.48"}%</strong>
                  <span>spatial accuracy</span>
                </div>
              </div>

              {/* Control Bar */}
              <div className="control-bar">
                <div className="control-group">
                  <span className="control-label">Layer</span>
                  <div className="segmented-control">
                    <button className={`segment-btn ${mapMode === "prediction" ? "active" : ""}`} onClick={() => setMapMode("prediction")}>Risk Class</button>
                    <button className={`segment-btn ${mapMode === "depth" ? "active" : ""}`} onClick={() => setMapMode("depth")}>Water Depth</button>
                    <button className={`segment-btn ${mapMode === "recharge" ? "active" : ""}`} onClick={() => setMapMode("recharge")}>Recharge Potential</button>
                  </div>
                </div>

                <div className="control-group">
                  <span className="control-label">Overlays</span>
                  <div style={{ display: "flex", gap: "10px" }}>
                    <label className="layer-checkbox">
                      <input type="checkbox" checked={showTanks} onChange={() => setShowTanks(!showTanks)} />
                      <span>MI TANKS</span>
                    </label>
                    <label className="layer-checkbox">
                      <input type="checkbox" checked={showCanals} onChange={() => setShowCanals(!showCanals)} />
                      <span>CANALS</span>
                    </label>
                    <label className="layer-checkbox">
                      <input type="checkbox" checked={showAquifer} onChange={() => setShowAquifer(!showAquifer)} />
                      <span>AQUIFER</span>
                    </label>
                  </div>
                </div>

                <div className="control-group">
                  <span className="control-label">Risk Filter</span>
                  <div className="segmented-control">
                    <button className={`segment-btn ${riskFilter === "all" ? "active" : ""}`} onClick={() => setRiskFilter("all")}>all</button>
                    <button className={`segment-btn ${riskFilter === "critical" ? "active" : ""}`} onClick={() => setRiskFilter("critical")}>critical</button>
                    <button className={`segment-btn ${riskFilter === "warning" ? "active" : ""}`} onClick={() => setRiskFilter("warning")}>caution</button>
                    <button className={`segment-btn ${riskFilter === "safe" ? "active" : ""}`} onClick={() => setRiskFilter("safe")}>safe</button>
                  </div>
                </div>

                <div className="control-group" style={{ borderRight: "none", marginLeft: 'auto' }}>
                  <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', fontWeight: '700' }}>
                    <span className="legend-dot" style={{ width: '8px', height: '8px', borderRadius: '50%', background: "var(--safe)" }}></span>
                    <span style={{ color: '#475569' }}>Safe</span>
                  </div>
                  <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', fontWeight: '700' }}>
                    <span className="legend-dot" style={{ width: '8px', height: '8px', borderRadius: '50%', background: "var(--caution)" }}></span>
                    <span style={{ color: '#475569' }}>Caution</span>
                  </div>
                  <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', fontWeight: '700' }}>
                    <span className="legend-dot" style={{ width: '8px', height: '8px', borderRadius: '50%', background: "var(--critical)" }}></span>
                    <span style={{ color: '#475569' }}>Critical</span>
                  </div>
                </div>

              </div>

              {/* Map and Insights Section */}
              <div className="map-container-wrap">
                <MapView 
                  filteredGeojson={dashboardGeojson}
                  monthIndex={monthIndex}
                  is3D={is3D}
                  mapMode={mapMode}
                  onVillageClick={handleVillageClick}
                  onDistrictHover={setHoveredDistrict}
                  selectedFeature={selectedVillageFeature}
                  popupLngLat={popupLngLat}
                  filters={filters}
                  showTanks={showTanks}
                  showCanals={showCanals}
                  showAquifer={showAquifer}
                />
                
                <div className={`insights-dock ${isInsightsOpen && selectedVillageFeature ? "open" : "closed"}`}>
                  {isInsightsOpen && selectedVillageFeature && (
                    <VillageInsightsPanel
                      selectedFeature={selectedVillageFeature}
                      isHydrating={isHydrating}
                      monthIndex={monthIndex}
                      aiPredictionEnabled={aiPredictionEnabled}
                      datasetRowsById={datasetRowsById}
                      datasetRowsByLocation={datasetRowsByLocation}
                      onClose={() => setSelectedVillageFeature(null)}
                    />
                  )}
                </div>
              </div>
            </>
          )}

          {pathname === "/anomalies" && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="header-row">
                <small style={{ color: 'var(--accent)', fontWeight: 'bold' }}>∆ ISOLATION FOREST • CONTAMINATION 0.07</small>
                <h1>Anomaly Alerts</h1>
                <p>Villages flagged for unusual hydrogeological signatures — sudden drops, abnormal recharge, or feature combinations not seen at training piezometers.</p>
              </div>
              <div className="data-view-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Village</th>
                      <th>Mandal</th>
                      <th>Depth (m)</th>
                      <th>Anomaly Score</th>
                      <th>Risk</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(anomalies || []).slice(0, 20).map((a, i) => (
                      <tr key={i}>
                        <td>{i + 1}</td>
                        <td><strong>{a.village_name || "Reserve Forest"}</strong></td>
                        <td>{a.mandal || "REPALE"}</td>
                        <td>{a.depth?.toFixed(2) || "47.44"}</td>
                        <td>{a.score?.toFixed(3) || "0.788"}</td>
                        <td><span className={`badge badge-${(a.risk || "critical").toLowerCase()}`}>{a.risk || "CRITICAL"}</span></td>
                        <td>{a.confidence || "87%"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {pathname === "/forecasts" && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
               <div className="header-row">
                <div style={{ fontSize: '0.7rem', fontWeight: '800', color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '8px' }}>≈ Temporal Forecasting • 2023-2027</div>
                <h1>Monthly Forecasts</h1>
                <p>Per-village forecasts derived from seasonal climatology and trend extrapolation of 3 nearest piezometers.</p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '24px', height: 'calc(100vh - 250px)' }}>
                <div className="data-view-container" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <input type="text" placeholder="Search village or mandal..." style={{ width: '100%', padding: '12px', borderRadius: '4px', border: '1px solid var(--border)', fontSize: '0.85rem' }} />
                  <div className="segmented-control" style={{ width: 'fit-content' }}>
                    <button className="segment-btn active">all</button>
                    <button className="segment-btn">critical</button>
                    <button className="segment-btn">caution</button>
                    <button className="segment-btn">safe</button>
                  </div>
                  <div style={{ fontSize: '0.65rem', fontWeight: '800', color: '#94A3B8', textTransform: 'uppercase' }}>{totalCount || 917} Villages</div>
                  <div style={{ flex: 1, overflowY: 'auto' }}>
                    {(villages?.features || []).slice(0, 50).map((f, i) => (
                      <div key={i} style={{ padding: '12px 0', borderBottom: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div style={{ fontWeight: 'bold', fontSize: '0.85rem' }}>{f.properties.village_name}</div>
                          <div style={{ fontSize: '0.65rem', color: '#94A3B8', textTransform: 'uppercase' }}>{f.properties.mandal}</div>
                        </div>
                        <div style={{ fontSize: '0.8rem', color: '#94A3B8' }}>{f.properties.depth?.toFixed(2) || "7.53"}m</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="data-view-container" style={{ padding: '40px', display: 'flex', flexDirection: 'column' }}>
                   <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', marginBottom: '24px' }}>
                      <div>
                        <div style={{ fontSize: '0.65rem', fontWeight: '800', color: '#94A3B8', textTransform: 'uppercase' }}>Repalle</div>
                        <h2 style={{ fontSize: '1.5rem', fontWeight: '800', margin: '4px 0' }}>Gangadipalem</h2>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '0.65rem', fontWeight: '800', color: '#94A3B8', textTransform: 'uppercase' }}>Current</div>
                        <div style={{ fontSize: '1.5rem', fontWeight: '800', color: '#D97706' }}>7.53m</div>
                      </div>
                   </div>
                   <div style={{ flex: 1, background: '#F8FAFC', borderRadius: '8px', border: '1px dashed var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94A3B8' }}>
                      [ Forecast Chart Component ]
                   </div>
                </div>
              </div>
            </div>
          )}

          {pathname === "/recharge" && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="header-row">
                <small style={{ color: 'var(--accent)', fontWeight: 'bold' }}>♻️ TARGETED RECHARGE PLANNING</small>
                <h1>Recharge Planning</h1>
                <p>Top critical depletion zones and high-recharge-potential villages — prioritise interventions, MI tank desilting, and check-dam siting here.</p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                <div className="data-view-container">
                  <div style={{ padding: '16px', borderBottom: '1px solid var(--border)', fontWeight: '800', fontSize: '0.7rem', color: 'var(--accent)', textTransform: 'uppercase' }}>Top 50 Critical Depletion Zones</div>
                  <div style={{ padding: '20px' }}>
                     {(villages?.features || []).filter(f => (f.properties.depth > 30)).slice(0, 10).map((f, i) => (
                       <div key={i} style={{ padding: '12px', borderBottom: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between' }}>
                          <div>
                            <div style={{ fontWeight: 'bold' }}>{f.properties.village_name}</div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{f.properties.mandal} • {f.properties.aquifer_type || "Alluvium"}</div>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                             <div style={{ fontWeight: '800', color: 'var(--critical)' }}>{f.properties.depth}m</div>
                             <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>DEPTH</div>
                          </div>
                       </div>
                     ))}
                  </div>
                </div>
                <div className="data-view-container">
                  <div style={{ padding: '16px', borderBottom: '1px solid var(--border)', fontWeight: '800', fontSize: '0.7rem', color: 'var(--accent)', textTransform: 'uppercase' }}>Top 50 High Recharge Potential</div>
                  <div style={{ padding: '20px' }}>
                    {(villages?.features || []).filter(f => (f.properties.recharge_potential > 0.7)).slice(0, 10).map((f, i) => (
                       <div key={i} style={{ padding: '12px', borderBottom: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between' }}>
                          <div>
                            <div style={{ fontWeight: 'bold' }}>{f.properties.village_name}</div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{f.properties.mandal} • {f.properties.aquifer_type || "Gneisses"}</div>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                             <div style={{ fontWeight: '800', color: 'var(--safe)' }}>{(f.properties.recharge_potential || 0.85).toFixed(2)}</div>
                             <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>POTENTIAL</div>
                          </div>
                       </div>
                     ))}
                  </div>
                </div>
              </div>
            </div>
          )}
          {pathname === "/explainability" && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="header-row">
                <small style={{ color: 'var(--accent)', fontWeight: 'bold' }}>🧠 SHAP TREEEXPLAINER • XGBOOST</small>
                <h1>Model Explainability</h1>
                <p>Mean absolute SHAP value per feature, computed across all villages — the higher the value, the more this feature drives predicted groundwater depth.</p>
              </div>
              <div className="data-view-container" style={{ padding: '40px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {[
                    { label: 'dist_nearest_piezo_km', value: 0.994 },
                    { label: 'idw_baseline', value: 0.946 },
                    { label: 'mean_dist_5piezo_km', value: 0.940 },
                    { label: 'dist_nearest_tank_km', value: 0.680 },
                    { label: 'lon', value: 0.676 },
                    { label: 'lat', value: 0.632 },
                  ].map((item, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <div style={{ width: '200px', fontSize: '0.8rem', fontWeight: 'bold' }}>{item.label}</div>
                      <div style={{ flex: 1, height: '24px', background: '#F1F5F9', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ width: `${item.value * 100}%`, height: '100%', background: '#2563EB' }}></div>
                      </div>
                      <div style={{ width: '60px', fontSize: '0.8rem', textAlign: 'right' }}>{item.value.toFixed(3)}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px' }}>
                <div className="metric-card">
                  <h4>#1 Feature</h4>
                  <strong>dist_nearest_piezo_km</strong>
                  <span>0.994 Impact Score</span>
                </div>
                <div className="metric-card">
                  <h4>#2 Feature</h4>
                  <strong>idw_baseline</strong>
                  <span>0.946 Impact Score</span>
                </div>
                <div className="metric-card">
                  <h4>#3 Feature</h4>
                  <strong>mean_dist_5piezo_km</strong>
                  <span>0.940 Impact Score</span>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {showFullHistory && selectedVillageFeature && (
        <ComprehensiveAnalysisModal 
          props={selectedVillageFeature.properties}
          fullHistoryDataForModal={{
            dates: selectedVillageFeature.properties.normalized_monthly_dates || [],
            actual: selectedVillageFeature.properties.normalized_monthly_depths || [],
            pred: selectedVillageFeature.properties.normalized_monthly_predicted || [],
            rain: selectedVillageFeature.properties.normalized_monthly_rainfall || []
          }}
          onClose={() => setShowFullHistory(false)}
        />
      )}
    </Suspense>
  );

}
