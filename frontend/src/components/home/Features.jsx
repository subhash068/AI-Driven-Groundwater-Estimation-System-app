import React from "react";

const FEATURES = [
  { name: "Village Prediction", detail: "Click any village and inspect groundwater estimate instantly." },
  { name: "Pumping Simulator", detail: "Adjust pumping intensity and see projected response." },
  { name: "Anomaly Detection", detail: "Identify unusual groundwater drops before they become crises." },
  { name: "Time-Series Trends", detail: "Explore groundwater history from 1998 to 2024." }
];

export function Features() {
  return (
    <section className="home-section reveal-up">
      <div className="section-head">
        <p className="section-chip">Feature Showcase</p>
        <h2>Capabilities Built for Action</h2>
      </div>
      <div className="feature-grid">
        {FEATURES.map((feature) => (
          <article key={feature.name} className="feature-card">
            <h3>{feature.name}</h3>
            <p>{feature.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
