import React from 'react';
import { CollapsiblePanel } from './UI';
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
  districtHoverData,
  trendHighlights,
  simulatorVillageId,
  setSimulatorVillageId,
  simulationInputs,
  setSimulationInputs,
  simulation,
  simulationLoading,
  simulationError,
  isOpen
}) {
  const { state, district, mandal, villageName } = filters;
  const { stateOptions, districtOptions, mandalOptions, villageOptions } = options;
  const activeDistrictData = hoveredDistrict ? districtHoverData?.[hoveredDistrict] : null;
  const comparisonDistrict = hoveredDistrict
    ? Object.keys(districtHoverData || {}).find((districtName) => districtName !== hoveredDistrict)
    : null;
  const comparisonDistrictData = comparisonDistrict ? districtHoverData?.[comparisonDistrict] : null;
  const selectedClassSet = new Set(selectedLulcClasses || []);
  const panelKey = "default";

  const toggleLulcClass = (classKey) => {
    setSelectedLulcClasses((prev) => {
      const current = Array.isArray(prev) ? prev : [];
      if (current.includes(classKey)) {
        return current.filter((k) => k !== classKey);
      }
      return [...current, classKey];
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
          <CollapsiblePanel title="District and Village" defaultOpen={true} key={`district-${panelKey}`}>
            <label>
              State
              <select
                value={state}
                onChange={(e) => onFilterChange('state', e.target.value)}
              >
                <option value="">All States</option>
                {stateOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              District Selector
              <select
                value={district}
                onChange={(e) => onFilterChange('district', e.target.value)}
              >
                <option value="">{state ? "All Districts" : "All Districts"}</option>
                {districtOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Mandal
              <select
                value={mandal}
                onChange={(e) => onFilterChange('mandal', e.target.value)}
                disabled={!district}
              >
                <option value="">{district ? "All Mandals" : "Select district first"}</option>
                {mandalOptions.map((item) => (
                  <option key={`${item.district}-${item.value}`} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label>
              Village
              <select 
                value={villageName} 
                onChange={(e) => onFilterChange('villageName', e.target.value)}
                disabled={!mandal}
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
              <input type="checkbox" checked={is3D} onChange={() => setIs3D(!is3D)} />
              3D View
            </label>
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
                checked={showLulc}
                onChange={() => setShowLulc(!showLulc)}
              />
              LULC
            </label>
            <label className="toggle" title="Groundwater anomaly detection layer">
              <input
                type="checkbox"
                checked={showAnomalies}
                onChange={() => setShowAnomalies(!showAnomalies)}
                aria-label="Groundwater anomaly detection layer"
              />
              Anomalies
            </label>
            {showAnomalies && (
              <div className="anomaly-severity-filter">
                <div className="anomaly-filter-actions">
                  <button
                    type="button"
                    className="anomaly-filter-btn anomaly-filter-btn-critical"
                    onClick={() => setSelectedAnomalyTypes(["Severe drop"])}
                  >
                    Show Critical Only
                  </button>
                  <button
                    type="button"
                    className="anomaly-filter-btn"
                    onClick={() => setSelectedAnomalyTypes(["Severe drop", "Moderate drop", "Normal", "Rise"])}
                  >
                    Reset
                  </button>
                </div>
                <label className="toggle anomaly-filter-toggle">
                  <input
                    type="checkbox"
                    checked={selectedAnomalyTypes.length === 4}
                    onChange={(event) => {
                      setSelectedAnomalyTypes(
                        event.target.checked ? ["Severe drop", "Moderate drop", "Normal", "Rise"] : []
                      );
                    }}
                  />
                  All
                </label>
                <div className="anomaly-type-grid">
                  {["Severe drop", "Moderate drop", "Normal", "Rise"].map((type) => (
                    <label key={type} className="toggle anomaly-filter-toggle">
                      <input
                        type="checkbox"
                        checked={selectedAnomalyTypes.includes(type)}
                        onChange={() => {
                          setSelectedAnomalyTypes((current) =>
                            current.includes(type)
                              ? current.filter((item) => item !== type)
                              : [...current, type]
                          );
                        }}
                      />
                      {type}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <label className="toggle">
              <input
                type="checkbox"
                checked={showRecharge}
                onChange={() => setShowRecharge(!showRecharge)}
              />
              Aquifer
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
            <label className="toggle">
              <input
                type="checkbox"
                checked={showDistrictBoundaries}
                onChange={() => setShowDistrictBoundaries(!showDistrictBoundaries)}
              />
              District Boundaries
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showMandalBoundaries}
                onChange={() => setShowMandalBoundaries(!showMandalBoundaries)}
              />
              Mandal Boundaries
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

          <CollapsiblePanel title="Prediction Lab" defaultOpen={false} key={`prediction-${panelKey}`}>
            <label className="toggle" style={{ marginBottom: '12px' }}>
              <input
                type="checkbox"
                checked={highRiskOnly}
                onChange={() => setHighRiskOnly((prev) => !prev)}
              />
              High-risk only map
            </label>
            <p className="lulc-chooser-caption" style={{ marginTop: 0, marginBottom: '12px' }}>
              Focus the dashboard on villages with the highest risk signal.
            </p>

            <div className="space-y-3">
              <label className="block text-xs text-slate-300">
                Pumping
                <input
                  type="range"
                  min="0"
                  max={Math.max(200, Number(simulationInputs.pumping || 0) * 2 + 50)}
                  step="0.1"
                  value={simulationInputs.pumping}
                  onChange={(event) =>
                    setSimulationInputs((prev) => ({ ...prev, pumping: Number(event.target.value) }))
                  }
                  className="mt-2 w-full"
                />
                <div className="mt-1 flex items-center justify-between text-[11px] text-slate-400">
                  <span>0 hp</span>
                  <strong className="text-slate-100">{Number(simulationInputs.pumping || 0).toFixed(1)} hp</strong>
                </div>
              </label>

              <label className="block text-xs text-slate-300">
                Functioning Wells
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={simulationInputs.functioningWells}
                  onChange={(event) =>
                    setSimulationInputs((prev) => ({
                      ...prev,
                      functioningWells: Number(event.target.value),
                    }))
                  }
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-100"
                />
              </label>

              <label className="block text-xs text-slate-300">
                Draft per Well
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={simulationInputs.draft}
                  onChange={(event) =>
                    setSimulationInputs((prev) => ({
                      ...prev,
                      draft: Number(event.target.value),
                    }))
                  }
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-100"
                />
              </label>
            </div>

            <div className="mt-4 rounded border border-slate-700 bg-slate-900/80 p-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-300">Base GWL</span>
                <strong>{Number.isFinite(Number(simulation?.base_groundwater_level)) ? `${Number(simulation.base_groundwater_level).toFixed(2)} m` : "NA"}</strong>
              </div>
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="text-slate-300">Simulated GWL</span>
                <strong>{Number.isFinite(Number(simulation?.predicted_groundwater_level)) ? `${Number(simulation.predicted_groundwater_level).toFixed(2)} m` : "NA"}</strong>
              </div>
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="text-slate-300">Impact</span>
                <strong className={Number(simulation?.impact_delta || 0) > 0 ? "text-rose-300" : Number(simulation?.impact_delta || 0) < 0 ? "text-emerald-300" : "text-slate-100"}>
                  {simulation?.impact_label || "Stable"}
                </strong>
              </div>
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="text-slate-300">Risk</span>
                <strong className={simulation?.warning ? "text-amber-300" : "text-slate-100"}>
                  {simulation?.risk_level || "NA"}
                </strong>
              </div>
              {simulationLoading && (
                <p className="mt-3 rounded border border-sky-700/50 bg-sky-900/20 p-2 text-xs text-sky-100">
                  Recomputing simulation...
                </p>
              )}
              {simulation?.warning && (
                <p className="mt-3 rounded border border-amber-700/50 bg-amber-900/20 p-2 text-xs text-amber-100">
                  {simulation.warning}
                </p>
              )}
              {simulationError && (
                <p className="mt-3 rounded border border-rose-700/50 bg-rose-900/20 p-2 text-xs text-rose-100">
                  {simulationError}
                </p>
              )}
            </div>
          </CollapsiblePanel>

          <CollapsiblePanel title="Trend Highlights" defaultOpen={false} key={`trend-${panelKey}`}>
            {(!trendHighlights || trendHighlights.length === 0) ? (
              <p className="lulc-chooser-caption" style={{ marginTop: 0 }}>
                No growth-risk trends available for the current scope.
              </p>
            ) : (
              <div className="space-y-2">
                {trendHighlights.map((row) => (
                  <div key={row.village_id} className="rounded border border-rose-700/40 bg-rose-900/10 p-2 text-xs">
                    <p className="font-semibold text-rose-200">{row.village_name}</p>
                    <p className="text-slate-300">District: {row.district}</p>
                    <p className="text-slate-300">Built-up change: {Number(row.built_up_change_pct || 0).toFixed(2)}%</p>
                    <p className="text-slate-300">Groundwater proxy change: {Number(row.groundwater_change_proxy || 0).toFixed(2)} m</p>
                  </div>
                ))}
              </div>
            )}
          </CollapsiblePanel>

          {is3D && (
            <CollapsiblePanel title="Aquifer Geometry" defaultOpen={false} key={`aquifer-${panelKey}`}>
              <div className="aquifer-panel" style={{ marginTop: 0, paddingTop: 0, borderTop: 0 }}>
                <div className="aquifer-scene">
                  <AquiferScene
                    weatheredDepth={Number(selectedFeature?.properties?.weathered_rock || 10)}
                    fracturedDepth={Number(selectedFeature?.properties?.fractured_rock || 18)}
                  />
                </div>
              </div>
            </CollapsiblePanel>
          )}

          {hoveredDistrict && activeDistrictData && (
            <CollapsiblePanel title="Hover Insights" defaultOpen={true} key={`hover-${panelKey}`}>
              <div className="district-hover-card" style={{ background: 'transparent', border: 'none', padding: 0 }}>
                <h3 style={{ fontSize: '1rem', color: '#fff', marginBottom: '8px' }}>{hoveredDistrict}</h3>
                {activeDistrictData.summary && (
                  <>
                    <p className="district-hover-source">{activeDistrictData.summary.source}</p>
                    <div className="district-hover-stats">
                      <div>
                        <strong>{activeDistrictData.summary.villageCount}</strong>
                        <span>Villages</span>
                      </div>
                      <div>
                        <strong>
                          {activeDistrictData.summary.avgDepth !== null
                            ? `${activeDistrictData.summary.avgDepth}m`
                            : "NA"}
                        </strong>
                        <span>Avg Depth</span>
                      </div>
                      <div>
                        <strong>{activeDistrictData.summary.warningCount}</strong>
                        <span>Warning Zones</span>
                      </div>
                      <div>
                        <strong>{activeDistrictData.summary.criticalCount}</strong>
                        <span>Critical Zones</span>
                      </div>
                    </div>
                  </>
                )}

                {activeDistrictData.pumping && activeDistrictData.waterLevels && (
                  <>
                    <div className="district-hover-stats">
                      <div>
                        <strong>{activeDistrictData.pumping.recordCount}</strong>
                        <span>Pumping Records</span>
                      </div>
                      <div>
                        <strong>{activeDistrictData.waterLevels.avgWaterLevel}m</strong>
                        <span>Avg Level</span>
                      </div>
                    </div>
                    <div className="district-hover-section" style={{ marginTop: '12px' }}>
                      <strong style={{ fontSize: '0.8rem', color: '#94a3b8' }}>TOP PUMPING MANDALS</strong>
                      <ul style={{ paddingLeft: '16px', marginTop: '4px', fontSize: '0.8rem' }}>
                        {activeDistrictData.pumping.topMandals.map(m => (
                          <li key={m.mandal}>{m.mandal}: {m.wells} wells</li>
                        ))}
                      </ul>
                    </div>
                  </>
                )}
              </div>

              {comparisonDistrict && comparisonDistrictData && (
                <div className="district-hover-card" style={{ background: 'transparent', border: 'none', padding: 0, marginTop: '14px' }}>
                  <h4 style={{ fontSize: '0.9rem', color: '#7dd3fc', marginBottom: '8px' }}>
                    Compare with {comparisonDistrict}
                  </h4>
                  {comparisonDistrictData.summary && (
                    <>
                      <p className="district-hover-source">{comparisonDistrictData.summary.source}</p>
                      <div className="district-hover-stats">
                        <div>
                          <strong>{comparisonDistrictData.summary.villageCount}</strong>
                          <span>Villages</span>
                        </div>
                        <div>
                          <strong>
                            {comparisonDistrictData.summary.avgDepth !== null
                              ? `${comparisonDistrictData.summary.avgDepth}m`
                              : "NA"}
                          </strong>
                          <span>Avg Depth</span>
                        </div>
                        <div>
                          <strong>{comparisonDistrictData.summary.warningCount}</strong>
                          <span>Warning Zones</span>
                        </div>
                        <div>
                          <strong>{comparisonDistrictData.summary.criticalCount}</strong>
                          <span>Critical Zones</span>
                        </div>
                      </div>
                    </>
                  )}

                  {comparisonDistrictData.pumping && comparisonDistrictData.waterLevels && (
                    <>
                      <div className="district-hover-stats">
                        <div>
                          <strong>{comparisonDistrictData.pumping.recordCount}</strong>
                          <span>Pumping Records</span>
                        </div>
                        <div>
                          <strong>{comparisonDistrictData.waterLevels.avgWaterLevel}m</strong>
                          <span>Avg Level</span>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </CollapsiblePanel>
          )}
        </>
      )}
      </div>
    </aside>

  );
}
