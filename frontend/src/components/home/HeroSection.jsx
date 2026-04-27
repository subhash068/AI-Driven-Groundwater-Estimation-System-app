import React, { useEffect, useRef, useState } from "react";

function formatCount(value) {
  if (!Number.isFinite(Number(value))) return "N/A";
  return Number(value).toLocaleString();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function HeroSection({ onEnterDashboard, stats }) {
  const [eye, setEye] = useState({ x: 0, y: 0, angle: 0, active: false });
  const stageRef = useRef(null);
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

  useEffect(() => {
    const homePage = document.querySelector(".home-page");
    const stage = stageRef.current;

    if (!homePage || !stage) return undefined;

    const maxOffset = 18;

    const resetEye = () => {
      setEye({ x: 0, y: 0, angle: 0, active: false });
    };

    const updateEye = (event) => {
      const rect = stage.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const relativeX = event.clientX - rect.left;
      const relativeY = event.clientY - rect.top;
      const offsetX = clamp((relativeX - rect.width / 2) / (rect.width / 2), -1, 1);
      const offsetY = clamp((relativeY - rect.height / 2) / (rect.height / 2), -1, 1);
      const angle = Math.atan2(offsetY, offsetX) * (180 / Math.PI);

      setEye({
        x: offsetX * maxOffset,
        y: offsetY * maxOffset,
        angle,
        active: true
      });
    };

    homePage.addEventListener("pointermove", updateEye, { passive: true });
    homePage.addEventListener("pointerleave", resetEye);
    homePage.addEventListener("pointercancel", resetEye);

    return () => {
      homePage.removeEventListener("pointermove", updateEye);
      homePage.removeEventListener("pointerleave", resetEye);
      homePage.removeEventListener("pointercancel", resetEye);
    };
  }, []);

  const eyeStyle = {
    "--eye-x": `${eye.x}px`,
    "--eye-y": `${eye.y}px`,
    "--eye-angle": `${eye.angle}deg`,
    "--eye-glint-x": `${eye.x * -0.42}px`,
    "--eye-glint-y": `${eye.y * -0.42}px`
  };

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
        <div className="hero-abstract-stage" ref={stageRef}>
          <div className="hero-abstract-sheen hero-sheen-a" />
          <div className="hero-abstract-sheen hero-sheen-b" />
          <div className="hero-abstract-orb">
            <span className="hero-abstract-orbit hero-abstract-orbit-a" />
            <span className="hero-abstract-orbit hero-abstract-orbit-b" />
            <span className="hero-abstract-orbit hero-abstract-orbit-c" />
            <div className={`hero-abstract-core${eye.active ? " is-tracking" : ""}`} style={eyeStyle}>
              <span className="hero-abstract-core-ring" />
              <span className="hero-abstract-core-pupil" />
              <span className="hero-abstract-core-glint" />
            </div>
          </div>
          <div className="hero-abstract-strata" aria-hidden="true">
            <span className="hero-strata-layer hero-strata-water" />
            <span className="hero-strata-layer hero-strata-soil" />
            <span className="hero-strata-layer hero-strata-rock" />
          </div>
          <div className="hero-abstract-cards">
            {visualCards.map((item, index) => (
              <div key={item.label} className={`hero-abstract-card hero-abstract-card-${index + 1}`}>
                <p>{item.label}</p>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <div className="hero-abstract-footer">
            <div>
              <p>Geo Lens</p>
              <strong>Subsurface Atlas</strong>
            </div>
            <span>Signal Matrix</span>
          </div>
        </div>
      </div>
    </section>
  );
}
