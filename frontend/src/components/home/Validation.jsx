import React from "react";

function formatMetric(value, digits = 3) {
  if (!Number.isFinite(Number(value))) return "N/A";
  return Number(value).toFixed(digits);
}

export function Validation({ stats, loading, error }) {
  const sample = stats?.snapshot || {};
  const metrics = stats?.model || {};

  return (
    <section className="home-section reveal-up">
      <div className="section-head">
        <p className="section-chip">Validation</p>
        <h2>Measured Performance, Not Claims</h2>
      </div>
      <div className="validation-shell">
        <div className="validation-sample">
          <h3>Actual vs Predicted</h3>
          <p>
            <strong>Village:</strong> {sample.sample_village || "N/A"}
          </p>
          <p>
            <strong>Actual:</strong> {formatMetric(sample.actual_last_month, 2)} m
          </p>
          <p>
            <strong>Predicted:</strong> {formatMetric(sample.predicted_gwl, 2)} m
          </p>
        </div>
        <div className="validation-metrics">
          <div title="R2 indicates variance explained by the model. Higher is better.">
            <span>R2</span>
            <strong>{formatMetric(metrics.r2, 3)}</strong>
          </div>
          <div title="RMSE is root mean squared error in meters. Lower is better.">
            <span>RMSE</span>
            <strong>{formatMetric(metrics.rmse, 3)}</strong>
          </div>
          <div title="MAE is average absolute error in meters. Lower is better.">
            <span>MAE</span>
            <strong>{formatMetric(metrics.mae, 3)}</strong>
          </div>
        </div>
      </div>
      <p className="data-caption">
        {error
          ? "Validation metrics unavailable. Build homepage stats from model artifacts."
          : loading
            ? "Loading model validation metrics..."
            : "Evaluated on held-out data"}
      </p>
    </section>
  );
}
