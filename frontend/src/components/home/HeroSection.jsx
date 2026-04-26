import React from "react";

function formatCount(value) {
  if (!Number.isFinite(Number(value))) return "N/A";
  return Number(value).toLocaleString();
}

export function HeroSection({ onEnterDashboard, stats }) {
  const villagesCount = Number(stats?.villages);
  const highRiskCount = Number(stats?.high_risk_count);
  const sourceDistricts = Array.isArray(stats?.source_excel?.districts) ? stats.source_excel.districts : [];
  const coverageLabel = sourceDistricts.length ? sourceDistricts.join(" + ") : "district-scale coverage";

  const statCards = [
    { value: Number.isFinite(villagesCount) ? formatCount(villagesCount) : "N/A", label: "Villages" },
    { value: Number.isFinite(highRiskCount) ? formatCount(highRiskCount) : "N/A", label: "High Risk" },
    { value: "25+ Years", label: "Data" }
  ];

  const dynamicSubtitle = Number.isFinite(villagesCount)
    ? `Analyzing groundwater across ${formatCount(villagesCount)} villages with district-level intelligence and geospatial AI.`
    : "Estimate groundwater levels across multiple districts using limited sensors and geospatial AI.";

  return (
    <section className="home-section hero-shell">
      <div className="hero-copy reveal-up">
        <p className="section-chip">Groundwater Intelligence</p>
        <h1>AI-Driven Groundwater Intelligence</h1>
        <p className="hero-subtext">{dynamicSubtitle}</p>
        {sourceDistricts.length ? (
          <p className="hero-source-note">Coverage: {coverageLabel}</p>
        ) : null}
        <div className="hero-actions">
          <button type="button" className="home-btn home-btn-primary" onClick={onEnterDashboard}>
            Explore Dashboard
          </button>
          <a className="home-btn home-btn-secondary" href="#map-preview">
            View Map
          </a>
        </div>
        <div className="hero-stats" aria-label="project scale">
          {statCards.map((item) => (
            <div key={item.label} className="hero-stat-card">
              <strong>{item.value}</strong>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="hero-visual reveal-up delay-1" aria-hidden="true">
        <div className="hero-map-mock">
          <div className="pulse pulse-a" />
          <div className="pulse pulse-b" />
          <div className="pulse pulse-c" />
          <div className="hero-grid" />
          <div className="hero-overlay">
            <div>
              <p>Live Signals</p>
              <strong>Village Risk Streaming</strong>
            </div>
            <span>Geo-AI</span>
          </div>
        </div>
      </div>
    </section>
  );
}
