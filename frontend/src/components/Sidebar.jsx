import React from 'react';
import { CollapsiblePanel } from './UI';
import MapLayerController from './MapLayerController';
import AquiferScene from '../AquiferScene';

const LULC_CLASS_OPTIONS = [
  { key: "water", label: "Water", color: "#3B82F6" },
  { key: "trees", label: "Trees", color: "#4D7C0F" },
  { key: "flooded_vegetation", label: "Flooded Vegetation", color: "#9AD1B4" },
  { key: "crops", label: "Crops", color: "#E9D162" },
  { key: "built_area", label: "Built Area", color: "#DC2626" },
  { key: "bare_ground", label: "Bare Ground", color: "#D4D4D4" },
  { key: "snow_ice", label: "Snow/Ice", color: "#E5E7EB" },
  { key: "clouds", label: "Clouds", color: "#BDBDBD" },
  { key: "rangeland", label: "Rangeland", color: "#D6C29C" }
];

export function Sidebar({ 
  filters, 
  onFilterChange, 
  options, 
  is3D, 
  setIs3D, 
  showLulc, 
  setShowLulc,
  showGroundwaterLevels,
  setShowGroundwaterLevels,
  showConfidenceIntervals,
  setShowConfidenceIntervals,
  showPiezometers,
  setShowPiezometers,
  showWells,
  setShowWells,
  selectedAnomalyTypes,
  setSelectedAnomalyTypes,
  showDistrictBoundaries,
  setShowDistrictBoundaries,
  showMandalBoundaries,
  setShowMandalBoundaries,
  showStateBoundary,
  setShowStateBoundary,
  selectedLulcClasses,
  setSelectedLulcClasses,
  highRiskOnly,
  setHighRiskOnly,
  selectedFeature,
  hoveredDistrict,
  onNavigateHome,
  loading,
  showAnomalies,
  setShowAnomalies,
  showRecharge,
  setShowRecharge,
  showAquifer,
  setShowAquifer,
  showSoil,
  setShowSoil,
  showRainfall,
  setShowRainfall,
  showCanals,
  setShowCanals,
  showStreams,
  setShowStreams,
  showDrains,
  setShowDrains,
  showTanks,
  setShowTanks,
  showDemSurface,
  setShowDemSurface,
  showModelIdwDiff,
  setShowModelIdwDiff,
  showErrorMap,
  setShowErrorMap,
  districtHoverData,
  trendHighlights,
  simulatorVillageId,
  setSimulatorVillageId,
  simulationInputs,
  setSimulationInputs,
  simulation,
  simulationLoading,
  simulationError,
  isOpen,
  baseMapTheme,
  setBaseMapTheme,
  mapMode,
  setMapMode
}) {
  const { state, district, mandal, villageName } = filters || {};
  const { stateOptions = [], districtOptions = [], mandalOptions = [], villageOptions = [] } = options || {};
  const activeDistrictData = hoveredDistrict ? districtHoverData?.[hoveredDistrict] : null;
  const comparisonDistrict = hoveredDistrict
    ? Object.keys(districtHoverData || {}).find((districtName) => districtName !== hoveredDistrict)
    : null;
  const comparisonDistrictData = comparisonDistrict ? districtHoverData?.[comparisonDistrict] : null;
  const selectedClassSet = new Set(selectedLulcClasses || []);
  const panelKey = "default";

  const toggleLulcClass = (classKey) => {
    setSelectedLulcClasses((prev) => {
      const next = new Set(prev);
      if (next.has(classKey)) next.delete(classKey);
      else next.add(classKey);
      return Array.from(next);
    });
  };

  return (
    <aside className={`panel ${isOpen ? "is-open" : ""}`}>
      <div className="panel-header">
        <div>
          <h1>Dashboard</h1>
        </div>
        <div className="sidebar-header-actions">
          <button type="button" className="panel-link" onClick={onNavigateHome}>
            Home
          </button>
        </div>
      </div>
      <div className="panel-body">
      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '20px' }}>
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="skeleton" style={{ height: '40px', width: '100%' }}></div>
          ))}
        </div>
      ) : (
        <>
          <div className="sidebar-priority-controls" style={{ 
            marginBottom: '20px', 
            padding: '4px 0 16px', 
            borderBottom: '1px solid rgba(0, 229, 255, 0.1)' 
          }}>
            <MapLayerController mode={mapMode} setMode={setMapMode} />
            
            <div className="panel-kicker" style={{ marginTop: '16px', marginBottom: '8px' }}>Base Map Theme</div>
            <select
              value={baseMapTheme}
              onChange={(e) => setBaseMapTheme(e.target.value)}
              className="sidebar-select-premium"
              style={{ 
                width: '100%',
                padding: '10px 12px', 
                borderRadius: '8px', 
                background: 'rgba(15, 23, 42, 0.6)', 
                color: '#fff', 
                border: '1px solid rgba(56, 189, 248, 0.2)',
                fontSize: '0.85rem',
                outline: 'none',
                cursor: 'pointer'
              }}
            >
              <option value="satellite">Satellite (Esri Imagery)</option>
              <option value="street">Street Map (OSM)</option>
              <option value="voyager">Voyager (Carto Light)</option>
            </select>
          </div>

          <CollapsiblePanel title="Location Filters" defaultOpen={true} key={`filters-${panelKey}`}>
            <label>
              State
              <select
                value={state || ""}
                onChange={(e) => onFilterChange("state", e.target.value)}
              >
                <option value="">All States</option>
                {stateOptions.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </label>
            <label>
              District
              <select
                value={district || ""}
                onChange={(e) => onFilterChange("district", e.target.value)}
                disabled={!state}
                style={{ opacity: !state ? 0.5 : 1, cursor: !state ? "not-allowed" : "pointer" }}
              >
                <option value="">All Districts</option>
                {districtOptions.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </label>
            <label>
              Mandal
              <select
                value={mandal || ""}
                onChange={(e) => onFilterChange("mandal", e.target.value)}
                disabled={!district}
                style={{ opacity: !district ? 0.5 : 1, cursor: !district ? "not-allowed" : "pointer" }}
              >
                <option value="">All Mandals</option>
                {mandalOptions.map((item) => (
                  <option key={`${item.district}-${item.value}`} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label>
              Village
              <select
                value={villageName || ""}
                onChange={(e) => onFilterChange("villageName", e.target.value)}
                disabled={!mandal}
                style={{ opacity: !mandal ? 0.5 : 1, cursor: !mandal ? "not-allowed" : "pointer" }}
              >
                <option value="">{mandal ? "All Villages" : "Select mandal first"}</option>
                {villageOptions.map((item) => (
                  <option key={`${item.district}-${item.mandal}-${item.value}`} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
          </CollapsiblePanel>

          <CollapsiblePanel title="Layer Toggles" defaultOpen={true} key={`layers-${panelKey}`}>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showRecharge}
                onChange={() => setShowRecharge(!showRecharge)}
              />
              AI Recharge Recommendation
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showAquifer}
                onChange={() => setShowAquifer(!showAquifer)}
              />
              Aquifer (Geological)
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showRainfall}
                onChange={() => setShowRainfall(!showRainfall)}
              />
              Rainfall Map
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showSoil}
                onChange={() => setShowSoil(!showSoil)}
              />
              Soil Types
            </label>

            <div style={{ marginTop: '12px', marginBottom: '6px', color: 'rgba(148, 163, 184, 0.9)', fontSize: '0.72rem', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Surface Water and Terrain
            </div>
            
            <label className="toggle">
              <input
                type="checkbox"
                checked={showCanals}
                onChange={() => setShowCanals(!showCanals)}
              />
              Canals
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showStreams}
                onChange={() => setShowStreams(!showStreams)}
              />
              Streams
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showDrains}
                onChange={() => setShowDrains(!showDrains)}
              />
              Drains
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showTanks}
                onChange={() => setShowTanks(!showTanks)}
              />
              Tanks/Water Bodies
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showDemSurface}
                onChange={() => setShowDemSurface(!showDemSurface)}
              />
              Terrain (DEM)
            </label>

            <div style={{ marginTop: '12px', marginBottom: '6px', color: 'rgba(148, 163, 184, 0.9)', fontSize: '0.72rem', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Analysis Layers
            </div>

            <label className="toggle">
              <input
                type="checkbox"
                checked={showGroundwaterLevels}
                onChange={() => setShowGroundwaterLevels(!showGroundwaterLevels)}
              />
              Groundwater Levels
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showConfidenceIntervals}
                onChange={() => setShowConfidenceIntervals(!showConfidenceIntervals)}
              />
              Confidence Intervals
            </label>
            <label className="toggle" title="Difference between Model and IDW baseline">
              <input
                type="checkbox"
                checked={showModelIdwDiff}
                onChange={() => {
                  setShowModelIdwDiff(!showModelIdwDiff);
                  if (!showModelIdwDiff) setShowErrorMap(false);
                }}
              />
              Model vs IDW (Delta)
            </label>
            <label className="toggle" title="Spatial error map for observed villages">
              <input
                type="checkbox"
                checked={showErrorMap}
                onChange={() => {
                  setShowErrorMap(!showErrorMap);
                  if (!showErrorMap) setShowModelIdwDiff(false);
                }}
              />
              Error Map (Observed)
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showPiezometers}
                onChange={() => setShowPiezometers(!showPiezometers)}
              />
              Piezometers
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showWells}
                onChange={() => setShowWells(!showWells)}
              />
              Wells
            </label>
          </CollapsiblePanel>

          {showLulc && (
            <CollapsiblePanel title="LULC Classes" defaultOpen={false} key={`lulc-${panelKey}-${showLulc ? "on" : "off"}`}>
              <div className="lulc-class-board">
                <p className="lulc-chooser-caption">Classes click to choose</p>
                <div className="lulc-class-grid">
                  {LULC_CLASS_OPTIONS.map((item) => {
                    const selected = selectedClassSet.has(item.key);
                    return (
                      <button
                        key={item.key}
                        type="button"
                        className={`lulc-class-chip ${selected ? "is-selected" : ""}`}
                        onClick={() => toggleLulcClass(item.key)}
                        title={item.label}
                      >
                        <span className="lulc-class-dot" style={{ background: item.color }} />
                        <span>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </CollapsiblePanel>
          )}

          {is3D && (
            <CollapsiblePanel title="Aquifer Geometry" defaultOpen={false} key={`aquifer-${panelKey}`}>
              <div className="aquifer-panel">
                <h3>Aquifer Scene (3D)</h3>
                <div className="aquifer-scene">
                  <AquiferScene />
                </div>
              </div>
            </CollapsiblePanel>
          )}

          {hoveredDistrict && (
            <CollapsiblePanel title="Hover Insights" defaultOpen={true} key={`hover-${panelKey}`}>
              <div className="district-hover-card">
                <h3>{hoveredDistrict}</h3>
                <p className="district-hover-source">Dynamic Regional Analysis</p>

                {activeDistrictData && (
                  <>
                    <div className="district-hover-stats">
                      <div>
                        <strong>{activeDistrictData.pumping?.recordCount || 0}</strong>
                        <span>Pumping Records</span>
                      </div>
                      <div>
                        <strong>{activeDistrictData.waterLevels?.avgWaterLevel ?? "NA"}m</strong>
                        <span>Avg Level</span>
                      </div>
                    </div>
                  </>
                )}

                {comparisonDistrictData?.pumping && comparisonDistrictData?.waterLevels && (
                  <>
                    <div className="district-hover-stats">
                      <div>
                        <strong>{comparisonDistrictData.pumping.recordCount}</strong>
                        <span>Pumping Records</span>
                      </div>
                      <div>
                        <strong>{comparisonDistrictData.waterLevels.avgWaterLevel ?? "NA"}m</strong>
                        <span>Avg Level</span>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </CollapsiblePanel>
          )}
        </>
      )}
      </div>
    </aside>
  );
}
