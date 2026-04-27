import React, { useEffect, useRef, useState } from "react";

function formatCount(value) {
  if (!Number.isFinite(Number(value))) return "N/A";
  return Number(value).toLocaleString();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function HeroSection({ onEnterDashboard, stats }) {
  const villagesCount = Number(stats?.villages);
  const modelR2 = Number(stats?.model?.r2);
  const sourceDistricts = Array.isArray(stats?.source_excel?.districts) ? stats.source_excel.districts : [];
  const coverageLabel = sourceDistricts.length ? sourceDistricts.join(" + ") : "district-scale coverage";
  const visualCards = [
    {
      label: "Recharge Field",
      value: Number.isFinite(villagesCount) ? `${formatCount(villagesCount)} Villages` : "Hydro Atlas"
    },
    {
      label: "Model Health",
      value: Number.isFinite(modelR2) ? `R2 ${modelR2.toFixed(3)}` : "Live Sync"
    },
    {
      label: "District Mesh",
      value: sourceDistricts.length ? sourceDistricts.join(" / ") : "Layered Scan"
    }
  ];

  const statCards = [
    { value: Number.isFinite(villagesCount) ? formatCount(villagesCount) : "N/A", label: "Villages" },
    { value: sourceDistricts.length ? formatCount(sourceDistricts.length) : "N/A", label: "Districts" },
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
        <div className="hero-info-stack">
          <div className="hero-info-cards">
            {visualCards.map((item, index) => (
              <div key={item.label} className="hero-info-card">
                <p>{item.label}</p>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <div className="hero-info-footer">
            <div className="hero-info-lens">
              <p>Geo Lens</p>
              <strong>Subsurface Atlas</strong>
            </div>
            <span className="hero-info-matrix">Signal Matrix</span>
          </div>
        </div>
      </div>
    </section>
  );
}
