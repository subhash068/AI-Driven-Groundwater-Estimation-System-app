import React from "react";

const IMPACT_ITEMS = [
  { title: "Farmers", detail: "Better irrigation planning and crop resilience." },
  { title: "Government", detail: "Data-backed policy and groundwater governance." },
  { title: "Sustainability", detail: "Stronger water conservation and recharge action." }
];

export function ImpactSection() {
  return (
    <section className="home-section reveal-up">
      <div className="section-head">
        <p className="section-chip">Impact</p>
        <h2>Built for Real-World Outcomes</h2>
      </div>
      <div className="impact-grid">
        {IMPACT_ITEMS.map((item) => (
          <article key={item.title} className="impact-card">
            <h3>{item.title}</h3>
            <p>{item.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
