import React from "react";

const FLOW = [
  {
    title: "Piezometers",
    detail: "Sparse sensors with real observations."
  },
  {
    title: "Geo Data",
    detail: "LULC, aquifer, soil, and wells context."
  },
  {
    title: "AI Model",
    detail: "XGBoost with spatial neighborhood logic."
  },
  {
    title: "Village Predictions",
    detail: "Groundwater levels for decision-making."
  }
];

export function HowItWorks() {
  return (
    <section className="home-section reveal-up">
      <div className="section-head">
        <p className="section-chip">How It Works</p>
        <h2>We Solve Sparse Data with Geo-AI</h2>
      </div>
      <div className="flow-grid">
        {FLOW.map((step, index) => (
          <div key={step.title} className="flow-item">
            <span className="flow-step">{String(index + 1).padStart(2, "0")}</span>
            <h3>{step.title}</h3>
            <p>{step.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
