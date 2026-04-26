import React, { useState, useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, GeoJSON } from "react-leaflet";
import './LandingPage.css';
import { DISTRICT_HOVER_DATA } from '../constants/data';

function AnimatedCounter({ value, duration = 2000 }) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    let start = 0;
    const end = parseInt(value) || 0;
    if (start === end) return;
    
    let timer = setInterval(() => {
      start += Math.ceil(end / (duration / 20));
      if (start >= end) {
        setDisplayValue(end);
        clearInterval(timer);
      } else {
        setDisplayValue(start);
      }
    }, 20);

    return () => clearInterval(timer);
  }, [value, duration]);

  return <span>{displayValue.toLocaleString()}</span>;
}

function MiniMapPreview({ villages }) {
  const center = [15.91, 79.74];
  const previewFeatures = useMemo(() => {
    if (!villages) return null;
    return {
      ...villages,
      features: villages.features.slice(0, 100)
    };
  }, [villages]);

  return (
    <div className="mini-map-glass h-full w-full">
      <MapContainer 
        center={center} 
        zoom={6} 
        zoomControl={false} 
        dragging={false} 
        touchZoom={false} 
        scrollWheelZoom={false}
        doubleClickZoom={false}
        style={{ height: '100%', width: '100%', background: 'transparent' }}
      >
        <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png" />
        {previewFeatures && (
          <GeoJSON 
            data={previewFeatures} 
            style={{ color: '#00e5ff', weight: 1, fillOpacity: 0.2 }} 
          />
        )}
      </MapContainer>
    </div>
  );
}

function formatValue(value, digits = null, suffix = "") {
  if (value === null || value === undefined || value === "") return "N/A";
  if (typeof value === "number" && Number.isFinite(value)) {
    return `${digits !== null ? value.toFixed(digits) : value.toLocaleString()}${suffix}`;
  }
  return `${value}${suffix}`;
}

function buildLayerDetails(activeClass, districtData) {
  const pumping = districtData?.pumping;
  const waterLevels = districtData?.waterLevels;
  if (!activeClass?.label) return null;

  switch (activeClass.label) {
    case "Monsoon Draft":
      return pumping ? {
        metrics: [
          { label: "Source", value: pumping.source },
          { label: "Records", value: formatValue(pumping.recordCount) },
          { label: "Avg Draft / Well", value: formatValue(pumping.avgMonsoonDraft, 3) },
          { label: "Top Mandal", value: pumping.topMandals?.[0] ? `${pumping.topMandals[0].mandal} (${formatValue(pumping.topMandals[0].wells)})` : "N/A" }
        ],
        previewRows: pumping.sampleRows || []
      } : null;
    case "Non-Monsoon Draft":
      return pumping ? {
        metrics: [
          { label: "Source", value: pumping.source },
          { label: "Records", value: formatValue(pumping.recordCount) },
          { label: "Avg Draft / Well", value: formatValue(pumping.avgNonMonsoonDraft, 3) },
          { label: "Top Village", value: pumping.sampleRows?.[0] ? `${pumping.sampleRows[0].village} (${formatValue(pumping.sampleRows[0].wells)})` : "N/A" }
        ],
        previewRows: pumping.sampleRows || []
      } : null;
    case "Functioning Wells":
      return pumping ? {
        metrics: [
          { label: "Source", value: pumping.source },
          { label: "Records", value: formatValue(pumping.recordCount) },
          { label: "Avg Functioning Wells", value: formatValue(pumping.avgFunctioningWells, 2) },
          { label: "Peak Mandal", value: pumping.topMandals?.[0] ? `${pumping.topMandals[0].mandal} (${formatValue(pumping.topMandals[0].wells)})` : "N/A" }
        ],
        previewRows: pumping.sampleRows || []
      } : null;
    case "Filter Points":
      return waterLevels ? {
        metrics: [
          { label: "Source", value: waterLevels.source },
          { label: "Observation Sites", value: formatValue(waterLevels.recordCount) },
          { label: "Avg Water Level", value: formatValue(waterLevels.avgWaterLevel, 2, " m") },
          { label: "Distinct Aquifers", value: formatValue(waterLevels.aquifers?.length) }
        ],
        previewRows: []
      } : null;
    case "Principal Aquifer":
      return waterLevels ? {
        metrics: [
          { label: "Source", value: waterLevels.source },
          { label: "Dominant Aquifer", value: waterLevels.aquifers?.[0] ? `${waterLevels.aquifers[0].aquifer}` : "N/A" },
          { label: "Station Count", value: waterLevels.aquifers?.[0] ? formatValue(waterLevels.aquifers[0].count) : "N/A" },
          { label: "Aquifer Types", value: formatValue(waterLevels.aquifers?.length) }
        ],
        previewRows: []
      } : null;
    case "Water Level History":
      return waterLevels ? {
        metrics: [
          { label: "Source", value: waterLevels.source },
          { label: "Records", value: formatValue(waterLevels.recordCount) },
          { label: "Avg Water Level", value: formatValue(waterLevels.avgWaterLevel, 2, " m") },
          { label: "Sample Station", value: waterLevels.sampleStations?.[0] ? `${waterLevels.sampleStations[0].village} - ${waterLevels.sampleStations[0].location}` : "N/A" }
        ],
        previewRows: []
      } : null;
    case "Total Depth":
      return waterLevels ? {
        metrics: [
          { label: "Source", value: waterLevels.source },
          { label: "Records", value: formatValue(waterLevels.recordCount) },
          { label: "Avg Total Depth", value: formatValue(waterLevels.avgTotalDepth, 2, " m") },
          { label: "Sample Station", value: waterLevels.sampleStations?.[0] ? `${waterLevels.sampleStations[0].village} (${waterLevels.sampleStations[0].location})` : "N/A" }
        ],
        previewRows: []
      } : null;
    case "Stratification":
      return waterLevels ? {
        metrics: [
          { label: "Source", value: waterLevels.source },
          { label: "Primary Unit", value: waterLevels.aquifers?.[0] ? waterLevels.aquifers[0].aquifer : "N/A" },
          { label: "Layer Count", value: formatValue(waterLevels.aquifers?.length) },
          { label: "Layering Basis", value: "Monitoring aquifer mix" }
        ],
        previewRows: []
      } : null;
    default:
      return null;
  }
}

export function LandingPage({ totalVillages, districtCount, onEnterDashboard, villages, hydroClasses }) {
  const [activeClass, setActiveClass] = useState(hydroClasses?.[0] || {});
  const districtData = DISTRICT_HOVER_DATA?.Krishna;
  const layerSnapshot = useMemo(
    () => buildLayerDetails(activeClass, districtData),
    [activeClass, districtData]
  );
  const isPumpingLayer = ["Monsoon Draft", "Non-Monsoon Draft", "Functioning Wells"].includes(activeClass?.label);

  return (
    <div className="landing-wrapper">
      <div className="landing-container">
        
        {/* Hero Section */}
        <section className="hero-section">
          <div className="hero-content animate-fade-up">
            <div className="hero-badge">
              <span className="hero-badge-dot"></span>
              Live Monitoring System
            </div>
            
            <h1 className="hero-title">
              Spatial Intelligence<br/>for Groundwater
            </h1>
            
            <p className="hero-description">
              Connect recharge signals, aquifer response, and village-level groundwater risk in one decision-ready interface for Andhra Pradesh.
            </p>
            
            <div className="hero-actions delay-200 animate-fade-up">
              <button type="button" className="btn-primary" onClick={onEnterDashboard}>
                Launch Dashboard
              </button>
              <a className="btn-secondary" href="#explore">
                Explore Capabilities
              </a>
            </div>
            
            <div className="stats-container delay-300 animate-fade-up">
              <div className="stat-glass-card">
                <span className="stat-number"><AnimatedCounter value={totalVillages || 12400} /></span>
                <span className="stat-label-text">Villages Mapped</span>
              </div>
              <div className="stat-glass-card">
                <span className="stat-number"><AnimatedCounter value={districtCount || 26} /></span>
                <span className="stat-label-text">Districts Analyzed</span>
              </div>
              <div className="stat-glass-card">
                <span className="stat-number"><AnimatedCounter value={24} /></span>
                <span className="stat-label-text">Monthly Slices</span>
              </div>
            </div>
          </div>
          
          <div className="hero-visual-container animate-fade-up delay-200">
            <MiniMapPreview villages={villages} />
          </div>
        </section>

        {/* Features Section */}
        <section id="explore" className="features-grid">
          {[
            {
              icon: 'M12 3v13m0 0l-4-4m4 4l4-4M4 21h16',
              title: 'Recharge Intelligence',
              desc: 'Track recharge potential, deficits, and seasonal lag behavior across thousands of geographic boundaries.'
            },
            {
              icon: 'M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z',
              title: 'Predictive Status',
              desc: 'Visualize depth-to-water (DTW), forecast imminent stress, and inspect village-level conditions in real-time.'
            },
            {
              icon: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4',
              title: 'Geological Context',
              desc: 'Layer complex geology, surface water influence, and extraction pressure to understand deep aquifer mechanics.'
            }
          ].map((feature, i) => (
            <div key={i} className={`feature-glass-card animate-fade-up delay-${(i+1)*100}`}>
              <div className="feature-icon-wrapper">
                <svg width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d={feature.icon}/>
                </svg>
              </div>
              <h3 className="feature-title">{feature.title}</h3>
              <p className="feature-desc">{feature.desc}</p>
            </div>
          ))}
        </section>

        {/* Layer Chooser Section */}
        {hydroClasses && hydroClasses.length > 0 && (
          <section className="layer-section animate-fade-up delay-200">
            <h2 className="layer-section-title">Explore Dataset Layers</h2>
            <div className="layer-showcase">
              <div className="layer-list">
                {hydroClasses.map((item) => {
                  const isActive = activeClass.label === item.label;
                  return (
                    <button
                      key={item.label}
                      className={`layer-btn ${isActive ? 'active' : ''}`}
                      onClick={() => setActiveClass(item)}
                    >
                      <span className="layer-color-dot" style={{ color: item.color, backgroundColor: item.color }}></span>
                      <span style={{ fontSize: '1.1rem', fontWeight: isActive ? '600' : '400' }}>{item.label}</span>
                    </button>
                  );
                })}
              </div>
              
              <div className="layer-info" style={{ '--layer-color': activeClass.color || '#00e5ff' }}>
                <div className="layer-info-source">{activeClass.source}</div>
                <h3>{activeClass.label}</h3>
                <p>{activeClass.description}</p>
                {layerSnapshot?.metrics && (
                  <div className="layer-data-grid">
                    {layerSnapshot.metrics.map((item) => (
                      <div key={item.label} className="layer-data-item">
                        <span className="layer-data-label">{item.label}</span>
                        <strong className="layer-data-value">{item.value}</strong>
                      </div>
                    ))}
                  </div>
                )}
                {isPumpingLayer && layerSnapshot?.previewRows?.length > 0 && (
                  <div className="layer-sheet-preview">
                    <div className="layer-sheet-preview-head">
                      <span>Sheet Preview</span>
                      <span>{districtData?.pumping?.source || "Pumping Data.xlsx"}</span>
                    </div>
                    <div className="layer-sheet-scroll">
                      <table className="layer-sheet-table">
                        <thead>
                          <tr>
                            <th>Mandal</th>
                            <th>Village</th>
                            <th>Structure</th>
                            <th>Wells</th>
                            <th>Monsoon</th>
                            <th>Non-Monsoon</th>
                          </tr>
                        </thead>
                        <tbody>
                          {layerSnapshot.previewRows.map((row) => (
                            <tr key={`${row.mandal}-${row.village}`}>
                              <td>{row.mandal}</td>
                              <td>{row.village}</td>
                              <td>{row.structureType}</td>
                              <td>{formatValue(row.wells, 0)}</td>
                              <td>{formatValue(row.monsoonDraftHaM, 3)}</td>
                              <td>{formatValue(row.nonMonsoonDraftHaM, 3)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

      </div>
    </div>
  );
}
