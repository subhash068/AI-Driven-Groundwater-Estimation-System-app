import React from "react";

export function CTA({ onEnterDashboard }) {
  return (
    <section className="home-section reveal-up">
      <div className="cta-panel">
        <h2>Explore groundwater insights across your region</h2>
        <button type="button" className="home-btn home-btn-primary" onClick={onEnterDashboard}>
          Open Dashboard
        </button>
      </div>
    </section>
  );
}
