import { useState, useMemo, useEffect, lazy, Suspense } from "react";
import { DashboardTopBar, DashboardAnalyticsPanel, VillageInsightsPanel } from "./components/UI";
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
  const [highRiskOnly, setHighRiskOnly] = useState(false);
  const [monthIndex, setMonthIndex] = useState(0);
  const [aiPredictionEnabled, setAiPredictionEnabled] = useState(true);
  const [is3D, setIs3D] = useState(false);
  const [showLulc, setShowLulc] = useState(false);
  const [showGroundwaterLevels, setShowGroundwaterLevels] = useState(false);
  const [showPiezometers, setShowPiezometers] = useState(false);
  const [showWells, setShowWells] = useState(false);
  const [showConfidenceIntervals, setShowConfidenceIntervals] = useState(false);
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
  const [showModelIdwDiff, setShowModelIdwDiff] = useState(false);
  const [showErrorMap, setShowErrorMap] = useState(false);
  const [apiStatus, setApiStatus] = useState(() => getApiStatusSummary());
  const [modelUpgradeSummary, setModelUpgradeSummary] = useState(null);
  const [isHydrating, setIsHydrating] = useState(false);

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

  const dashboardGeojson = useMemo(() => {
    const merged = mergeVillageMapData(filteredGeojson, dashboardMapData);
    if (!merged) return null;
    if (!highRiskOnly) return merged;

    const features = (merged.features || []).filter(
      (feature) => {
        const risk = String(feature?.properties?.risk_level || "").toLowerCase();
        return risk === "critical" || risk === "high";
      }
    );

    return {
      ...merged,
      features
    };
  }, [filteredGeojson, dashboardMapData, highRiskOnly]);

  const dashboardStats = useMemo(() => {
    if (!dashboardGeojson) return { safe: 0, warning: 0, critical: 0, total: 0 };
    const stats = { safe: 0, warning: 0, critical: 0, total: dashboardGeojson.features.length };
    dashboardGeojson.features.forEach(f => {
      const depth = Number(f.properties?.monthly_depths?.[monthIndex] ?? f.properties?.depth ?? 0);
      if (depth >= 30) stats.critical++;
      else if (depth >= 20) stats.warning++;
      else stats.safe++;
    });
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
      <div className={`geo-layout dashboard-shell ${isSidebarOpen ? "sidebar-open" : "sidebar-closed"}`}>
        <button
          className="menu-button"
          type="button"
          aria-label="Toggle sidebar menu"
          aria-expanded={isSidebarOpen}
          onClick={() => setIsSidebarOpen((prev) => !prev)}
        >
          <span />
          <span />
          <span />
        </button>
        {isSidebarOpen && (
          <button
            type="button"
            className="sidebar-backdrop"
            aria-label="Close sidebar"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
        <Sidebar 
          filters={filters}
          onFilterChange={handleFilterChange}
          options={{ stateOptions, districtOptions, mandalOptions, villageOptions }}
          is3D={is3D}
          setIs3D={setIs3D}
          showLulc={showLulc}
          setShowLulc={setShowLulc}
          mapMode={mapMode}
          setMapMode={setMapMode}
          showGroundwaterLevels={showGroundwaterLevels}
          setShowGroundwaterLevels={setShowGroundwaterLevels}
          showConfidenceIntervals={showConfidenceIntervals}
          setShowConfidenceIntervals={setShowConfidenceIntervals}
          showPiezometers={showPiezometers}
          setShowPiezometers={setShowPiezometers}
          showWells={showWells}
          setShowWells={setShowWells}
          selectedAnomalyTypes={selectedAnomalyTypes}
          setSelectedAnomalyTypes={setSelectedAnomalyTypes}
          showDistrictBoundaries={showDistrictBoundaries}
          setShowDistrictBoundaries={setShowDistrictBoundaries}
          showMandalBoundaries={showMandalBoundaries}
          setShowMandalBoundaries={setShowMandalBoundaries}
          showStateBoundary={showStateBoundary}
          setShowStateBoundary={setShowStateBoundary}
          showRainfall={showRainfall}
          setShowRainfall={setShowRainfall}
          showCanals={showCanals}
          setShowCanals={setShowCanals}
          showStreams={showStreams}
          setShowStreams={setShowStreams}
          showDrains={showDrains}
          setShowDrains={setShowDrains}
          showTanks={showTanks}
          setShowTanks={setShowTanks}
          showDemSurface={showDemSurface}
          setShowDemSurface={setShowDemSurface}
          selectedLulcClasses={selectedLulcClasses}
          setSelectedLulcClasses={setSelectedLulcClasses}
          highRiskOnly={highRiskOnly}
          setHighRiskOnly={setHighRiskOnly}
          selectedFeature={selectedVillageFeature}
          hoveredDistrict={hoveredDistrict}
          showAnomalies={showAnomalies}
          setShowAnomalies={setShowAnomalies}
          showRecharge={showRecharge}
          setShowRecharge={setShowRecharge}
          showAquifer={showAquifer}
          setShowAquifer={setShowAquifer}
          showSoil={showSoil}
          setShowSoil={setShowSoil}
          showModelIdwDiff={showModelIdwDiff}
          setShowModelIdwDiff={setShowModelIdwDiff}
          showErrorMap={showErrorMap}
          setShowErrorMap={setShowErrorMap}
          onNavigateHome={() => typeof navigate === "function" && navigate("/")}
          loading={loading}
          districtHoverData={districtHoverData}
          trendHighlights={trendHighlights}
          simulatorVillageId={simulatorVillageId}
          setSimulatorVillageId={setSimulatorVillageId}
          simulationInputs={simulationInputs}
          setSimulationInputs={setSimulationInputs}
          simulation={simulation}
          simulationLoading={simulationLoading}
          simulationError={simulationError}
          isOpen={isSidebarOpen}
          baseMapTheme={baseMapTheme}
          setBaseMapTheme={setBaseMapTheme}
        />

        <section className="geo-workspace">
          <DashboardTopBar
            monthIndex={monthIndex}
            setMonthIndex={setMonthIndex}
            aiPredictionEnabled={aiPredictionEnabled}
            setAiPredictionEnabled={setAiPredictionEnabled}
            stats={dashboardStats}
            isFullDashboardOpen={isFullDashboardOpen}
            onToggleFullDashboard={() => setIsFullDashboardOpen((prev) => !prev)}
            scopeLabel={topbarScopeLabel}
          />
          {apiStatusMessage && (
            <div className="api-status-banner" role="status" aria-live="polite">
              <strong>Fallback mode:</strong> {apiStatusMessage}
            </div>
          )}
          {isFullDashboardOpen && (
            <DashboardAnalyticsPanel
              datasetAnalytics={datasetAnalytics}
              selectedFeature={selectedVillageFeature}
              modelUpgradeSummary={modelUpgradeSummary}
              onClose={() => setIsFullDashboardOpen(false)}
            />
          )}
          <div className={`geo-main ${isInsightsOpen ? "" : "insights-collapsed"}`}>
            <main className="map-wrap">
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
                showLulc={showLulc}
                showGroundwaterLevels={showGroundwaterLevels}
                showConfidenceIntervals={showConfidenceIntervals}
                showPiezometers={showPiezometers}
                showWells={showWells}
                selectedAnomalyTypes={selectedAnomalyTypes}
                showDistrictBoundaries={showDistrictBoundaries}
                showMandalBoundaries={showMandalBoundaries}
                showStateBoundary={showStateBoundary}
                stateBoundaryLayer={stateBoundaryLayer}
                selectedLulcClasses={selectedLulcClasses}
                showRecharge={showRecharge}
                showRainfall={showRainfall}
                showCanals={showCanals}
                showStreams={showStreams}
                showDrains={showDrains}
                showTanks={showTanks}
                showDemSurface={showDemSurface}
                showAquifer={showAquifer}
                showSoil={showSoil}
                showModelIdwDiff={showModelIdwDiff}
                showErrorMap={showErrorMap}
                villageDataError={error}
                villageDataSource={dataSource}
                datasetRowsById={datasetRowsById}
                datasetRowsByLocation={datasetRowsByLocation}
                anomalies={aiPredictionEnabled && showAnomalies ? anomalies : null}
                rechargeZones={aiPredictionEnabled && showRecharge ? rechargeZones : null}
                selectedDistrict={filters.district}
                baseMapTheme={baseMapTheme}
              />
            </main>
            <div className={`insights-dock ${isInsightsOpen ? "open" : "closed"}`}>
              {isInsightsOpen && (
                <>
                  <VillageInsightsPanel
                    selectedFeature={selectedVillageFeature}
                    isHydrating={isHydrating}
                    monthIndex={monthIndex}
                    aiPredictionEnabled={aiPredictionEnabled}
                    aquiferAnalytics={aquiferAnalytics}
                    datasetAnalytics={datasetAnalytics}
                    showPiezometers={showPiezometers}
                    datasetRowsById={datasetRowsById}
                    datasetRowsByLocation={datasetRowsByLocation}
                  />
                  <VillageActionPanel
                    selectedFeature={selectedVillageFeature}
                    aiPredictionEnabled={aiPredictionEnabled}
                    defaultMode={aiPredictionEnabled ? "live" : "batch"}
                  />
                </>
              )}
            </div>
          </div>
        </section>
      </div>
    </Suspense>
  );
}
