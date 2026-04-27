import React from "react";

function formatCount(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  if (!Number.isFinite(Number(value))) return "N/A";
  return Number(value).toLocaleString();
}

function formatTrend(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  if (!Number.isFinite(Number(value))) return "N/A";
  return `${Number(value).toFixed(2)} m/year`;
}

function formatDepth(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  if (!Number.isFinite(Number(value))) return "N/A";
  return `${Number(value).toFixed(2)} m`;
}

function getTrendClassification(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return { label: "N/A", tone: "neutral", icon: "⚪" };
  
  if (num < -0.02) return { label: "Improving", tone: "recharge", icon: "🔵" };
  if (num >= -0.02 && num <= 0.02) return { label: "Stable", tone: "stable", icon: "🟢" };
  if (num > 0.02 && num <= 0.05) return { label: "Moderate Depletion", tone: "warn", icon: "🟡" };
  if (num > 0.05) return { label: "Severe Depletion", tone: "critical", icon: "🔴" };
  
  return { label: "Stable", tone: "stable", icon: "🟢" };
}

function districtHasData(row) {
  const villages = Number(row?.villages);
  return Number.isFinite(villages) && villages > 0;
}

function districtValue(row, formatter, value) {
  if (!districtHasData(row)) return "Data not available";
  return formatter(value);
}

function formatTimestamp(isoString) {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    return d.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short"
    });
  } catch {
    return null;
  }
}

export function InsightsCards({ stats, loading, error }) {
  const sourceDistricts = Array.isArray(stats?.source_excel?.districts)
    ? stats.source_excel.districts.join(" + ")
    : null;
  const pumpingByDistrict = stats?.source_excel?.pumping?.district_counts || {};
  const piezometerByDistrict = stats?.source_excel?.piezometer?.district_counts || {};
  const hasSourceBreakdown = Object.keys(pumpingByDistrict).length > 0 || Object.keys(piezometerByDistrict).length > 0;
  const sourceDistrictRows = Array.from(
    new Set([...Object.keys(pumpingByDistrict), ...Object.keys(piezometerByDistrict)])
  )
    .sort((a, b) => a.localeCompare(b))
    .map((district) => ({
      district,
      pumping: Number(pumpingByDistrict[district]) || 0,
      piezometers: Number(piezometerByDistrict[district]) || 0
    }));
  const sourceMaxValue =
    sourceDistrictRows.length > 0
      ? Math.max(
          ...sourceDistrictRows.flatMap((row) => [row.pumping, row.piezometers])
        )
      : 0;
  const districtAggregation = Array.isArray(stats?.district_aggregation?.districts)
    ? stats.district_aggregation.districts
    : [];
  const comparisonInsight = stats?.district_aggregation?.comparison_insight;
  
  const trendClass = getTrendClassification(stats?.avg_trend_slope);

  const cards = [
    {
      title: "Villages Analyzed",
      value: formatCount(stats?.villages),
      description: "covered in the current dataset",
      tone: "stable"
    },
    {
      title: "Avg Groundwater Trend",
      value: formatTrend(stats?.avg_trend_slope),
      description: "mean long-term slope",
      tone: trendClass.tone,
      badge: trendClass,
      explanation: "Trend slope (m/year) represents long-term groundwater change (1998–2024). Values near zero (±0.01–0.03) indicate stable conditions, while higher positive values signal depletion and negative values indicate recharge."
    }
  ];

  return (
    <section className="home-section reveal-up">
      <div className="section-head">
        <p className="section-chip">AI Insights</p>
        <h2>From Raw Signals to Decisions</h2>
      </div>
      <div className="insights-grid">
        {cards.map((item) => (
          <article key={item.title} className={`insight-card ${item.tone}`}>
            <h3>{item.title}</h3>
            <strong>{item.value}</strong>
            <p>{item.description}</p>
            {item.badge && (
              <div className={`trend-badge ${item.badge.tone}`}>
                {item.badge.icon} {item.badge.label}
              </div>
            )}
            {item.explanation && <p className="insight-explanation">{item.explanation}</p>}
          </article>
        ))}
      </div>
      {districtAggregation.length > 0 && (
        <article className="district-compare-card">
          <div className="district-compare-head">
            <h3>Krishna vs NTR</h3>
            <span>Multi-District Intelligence System</span>
          </div>
          <div className="district-compare-table-wrap">
            <table className="district-compare-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  {districtAggregation.map((row) => (
                    <th key={row.district}>{row.district}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Villages</td>
                  {districtAggregation.map((row) => (
                    <td key={`${row.district}-villages`}>
                      {districtValue(row, formatCount, row.villages)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>Avg GWL</td>
                  {districtAggregation.map((row) => (
                    <td key={`${row.district}-gwl`}>
                      {districtValue(row, formatDepth, row.avg_groundwater_level)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>Avg Trend Slope</td>
                  {districtAggregation.map((row) => (
                    <td key={`${row.district}-trend`}>
                      {districtValue(row, formatTrend, row.avg_trend_slope)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>High-risk villages</td>
                  {districtAggregation.map((row) => (
                    <td key={`${row.district}-risk`}>
                      {districtValue(row, formatCount, row.high_risk_count)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>Trend</td>
                  {districtAggregation.map((row) => (
                    <td key={`${row.district}-arrow`}>
                      {districtHasData(row) ? (row.trend_arrow || "N/A") : "Data not available"}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="district-compare-note">
            {comparisonInsight || "District comparison insight will appear when both district datasets are available."}
          </p>
        </article>
      )}
      {hasSourceBreakdown && (
        <article className="source-card">
          <h3>Data Sources</h3>
          <p>Pumping Data.xlsx</p>
          <div className="source-grid">
            {Object.entries(pumpingByDistrict).map(([district, count]) => (
              <div key={`pump-${district}`}>
                <span>{district} Pumping</span>
                <strong>{Number(count).toLocaleString()}</strong>
              </div>
            ))}
          </div>
          <p>PzWaterLevel_2024.xlsx</p>
          <div className="source-grid">
            {Object.entries(piezometerByDistrict).map(([district, count]) => (
              <div key={`pz-${district}`}>
                <span>{district} Piezometers</span>
                <strong>{Number(count).toLocaleString()}</strong>
              </div>
            ))}
          </div>
          {sourceDistrictRows.length > 0 && sourceMaxValue > 0 && (
            <div className="source-chart">
              <h4>District-wise Source Coverage</h4>
              <div className="source-legend">
                <span className="source-dot source-dot-pumping" /> Pumping
                <span className="source-dot source-dot-piezometer" /> Piezometers
              </div>
              {sourceDistrictRows.map((row) => {
                const pumpingWidth = (row.pumping / sourceMaxValue) * 100;
                const piezometerWidth = (row.piezometers / sourceMaxValue) * 100;
                return (
                  <div key={`chart-${row.district}`} className="source-chart-row">
                    <p>{row.district}</p>
                    <div className="source-chart-bars">
                      <div className="source-track">
                        <div
                          className="source-bar source-bar-pumping"
                          style={{ width: `${pumpingWidth}%` }}
                        >
                          {row.pumping.toLocaleString()}
                        </div>
                      </div>
                      <div className="source-track">
                        <div
                          className="source-bar source-bar-piezometer"
                          style={{ width: `${piezometerWidth}%` }}
                        >
                          {row.piezometers.toLocaleString()}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </article>
      )}
      <div className="stats-meta-footer">
        {loading ? (
          <span className="meta-pipeline">Loading dataset-backed stats...</span>
        ) : error ? (
          <span className="meta-pipeline">Dataset stats unavailable. Build homepage stats from dataset.</span>
        ) : (
          <>
            <span className="meta-pipeline">
              Data Source: Computed from groundwater dataset (offline ML pipeline)
            </span>
            {stats?.meta?.generated_at && (
              <span className="meta-timestamp">
                Last updated: {formatTimestamp(stats.meta.generated_at)}
              </span>
            )}
          </>
        )}
      </div>
    </section>
  );
}
