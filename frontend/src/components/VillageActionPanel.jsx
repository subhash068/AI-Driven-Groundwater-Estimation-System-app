import React, { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";

function formatDepth(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "NA";
  return `${numeric.toFixed(2)} m`;
}

function formatConfidence(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "NA";
  return `${numeric.toFixed(0)}%`;
}

function titleCase(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/^\w/, (match) => match.toUpperCase());
}

function normalizeRisk(value, fallbackDepth = null) {
  const text = String(value || "").trim().toLowerCase();
  if (["critical", "severe", "high"].includes(text)) return "critical";
  if (["warning", "medium", "moderate"].includes(text)) return "warning";
  if (["safe", "low", "good"].includes(text)) return "safe";
  if (!Number.isFinite(Number(fallbackDepth))) return "warning";
  if (Number(fallbackDepth) >= 30) return "critical";
  if (Number(fallbackDepth) >= 20) return "warning";
  return "safe";
}

function deriveAlertStatus(riskLevel, anomalyFound, anomalyScore, currentDepth) {
  const normalized = normalizeRisk(riskLevel, currentDepth);
  if (anomalyFound && normalized !== "critical") {
    if (Number.isFinite(Number(anomalyScore)) && Number(anomalyScore) >= 0.75) {
      return "critical";
    }
    return "warning";
  }
  return normalized;
}

function formatMonthLabel(value, fallbackIndex = 0) {
  if (!value) {
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return monthNames[fallbackIndex % 12];
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

function buildForecastSeries(selectedFeature, forecastPayload, statusPayload) {
  const props = selectedFeature?.properties || {};
  const observedSeries =
    (Array.isArray(forecastPayload?.observed_series) && forecastPayload.observed_series.length
      ? forecastPayload.observed_series
      : Array.isArray(statusPayload?.observed_series) && statusPayload.observed_series.length
        ? statusPayload.observed_series
        : Array.isArray(props.monthly_depths_full) && props.monthly_depths_full.length
          ? props.monthly_depths_full.map((value, index) => ({
              label: String(props.monthly_depths_full_dates?.[index] || `Month ${index + 1}`),
              groundwater_depth: Number(value),
              kind: "observed"
            })).filter((point) => Number.isFinite(point.groundwater_depth)).slice(-6)
          : Array.isArray(props.monthly_depths) && props.monthly_depths.length
            ? props.monthly_depths.map((value, index) => ({
                label: String(props.monthly_depths_dates?.[index] || `Month ${index + 1}`),
                groundwater_depth: Number(value),
                kind: "observed"
              })).filter((point) => Number.isFinite(point.groundwater_depth)).slice(-6)
            : []);

  const forecastSeries =
    (Array.isArray(forecastPayload?.forecast_3_month) && forecastPayload.forecast_3_month.length
      ? forecastPayload.forecast_3_month
      : Array.isArray(statusPayload?.forecast_3_month) && statusPayload.forecast_3_month.length
        ? statusPayload.forecast_3_month
        : []).map((point, index) => ({
          label: formatMonthLabel(point.forecast_date, index),
          groundwater_depth: Number(point.predicted_groundwater_depth),
          kind: "forecast",
          lower: Number(point.predicted_lower),
          upper: Number(point.predicted_upper)
        })).filter((point) => Number.isFinite(point.groundwater_depth));

  return { observedSeries, forecastSeries };
}

function ForecastLineChart({ observedSeries, forecastSeries }) {
  const values = [...observedSeries, ...forecastSeries]
    .map((point) => Number(point.groundwater_depth))
    .filter((value) => Number.isFinite(value));

  if (!values.length) {
    return (
      <div className="forecast-empty-state">
        No observed or forecast series available for this village.
      </div>
    );
  }

  const width = 100;
  const height = 62;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 0.5);
  const allPoints = [...observedSeries, ...forecastSeries];
  const plotPoints = allPoints.map((point, index) => {
    const x = allPoints.length === 1 ? 6 : (index / (allPoints.length - 1)) * 88 + 6;
    const y = 48 - ((Number(point.groundwater_depth) - min) / span) * 30;
    return { ...point, x, y };
  });

  const observedPath = plotPoints
    .slice(0, observedSeries.length)
    .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");
  const forecastPath = plotPoints
    .slice(Math.max(observedSeries.length - 1, 0))
    .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");

  return (
    <div className="forecast-chart-shell">
      <svg viewBox={`0 0 ${width} ${height}`} className="forecast-chart" role="img" aria-label="Groundwater forecast chart">
        <defs>
          <linearGradient id="forecast-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.32" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <line x1="0" y1="12" x2="100" y2="12" className="forecast-grid-line" />
        <line x1="0" y1={48 - ((values[0] - min) / span) * 30} x2="100" y2={48 - ((values[0] - min) / span) * 30} className="forecast-grid-line forecast-grid-line-soft" />
        {observedPath && (
          <polyline points={observedPath} className="forecast-observed-line" />
        )}
        {forecastPath && (
          <polyline points={forecastPath} className="forecast-forecast-line" strokeDasharray="4 3" />
        )}
        <polygon
          points={`${observedPath || forecastPath} 94,48 6,48`}
          fill="url(#forecast-fill)"
          opacity="0.75"
        />
        {plotPoints.map((point, index) => (
          <circle
            key={`${point.kind}-${index}-${point.label}`}
            cx={point.x}
            cy={point.y}
            r="2.5"
            className={point.kind === "forecast" ? "forecast-point forecast-point-forecast" : "forecast-point forecast-point-observed"}
          >
            <title>{`${point.label}: ${Number(point.groundwater_depth).toFixed(2)} m`}</title>
          </circle>
        ))}
      </svg>
      <div className="forecast-axis-labels">
        {plotPoints.map((point, index) => (
          <span key={`${point.kind}-${point.label}-${index}`}>{point.label}</span>
        ))}
      </div>
    </div>
  );
}

export function VillageActionPanel({ selectedFeature, aiPredictionEnabled = true }) {
  const [status, setStatus] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const villageId = Number(selectedFeature?.properties?.village_id);
  const villageName = String(selectedFeature?.properties?.village_name || "Selected village");
  const district = String(selectedFeature?.properties?.district || "Unknown");
  const mandal = String(selectedFeature?.properties?.mandal || "Unknown");

  useEffect(() => {
    let active = true;
    if (!Number.isFinite(villageId)) {
      setStatus(null);
      setForecast(null);
      setAnomalies([]);
      setLoading(false);
      setError(null);
      return undefined;
    }

    (async () => {
      try {
        setLoading(true);
        setError(null);
        const statusPromise = api.getVillageStatus(villageId);
        const forecastPromise = aiPredictionEnabled
          ? api.getVillageForecast(villageId)
          : Promise.resolve(null);
        const anomaliesPromise = api.getAnomalies("json");
        const [nextStatus, nextForecast, nextAnomalies] = await Promise.all([
          statusPromise,
          forecastPromise,
          anomaliesPromise
        ]);

        if (!active) return;
        setStatus(nextStatus || null);
        setForecast(nextForecast || null);
        setAnomalies(Array.isArray(nextAnomalies) ? nextAnomalies : []);
      } catch (err) {
        if (!active) return;
        setError(err?.message || "Unable to load village forecast");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [villageId, aiPredictionEnabled]);

  const anomalyMatch = useMemo(() => {
    if (!Number.isFinite(villageId)) return null;
    return anomalies.find((item) => Number(item?.village_id) === villageId) || null;
  }, [anomalies, villageId]);

  const forecastObserved = Array.isArray(forecast?.observed_series) ? forecast.observed_series : [];
  const statusObserved = Array.isArray(status?.observed_series) ? status.observed_series : [];
  const currentDepth = Number(
    status?.current_depth ??
    forecastObserved[forecastObserved.length - 1]?.groundwater_depth ??
    statusObserved[statusObserved.length - 1]?.groundwater_depth ??
    selectedFeature?.properties?.actual_last_month ??
    selectedFeature?.properties?.predicted_groundwater_level ??
    selectedFeature?.properties?.depth
  );

  const riskLevel = titleCase(
    status?.risk_level ||
      selectedFeature?.properties?.risk_level ||
      selectedFeature?.properties?.risk ||
      "warning"
  );
  const alertStatus = deriveAlertStatus(
    riskLevel,
    Boolean(anomalyMatch),
    anomalyMatch?.anomaly_score,
    currentDepth
  );
  const confidenceScore = Number(
    forecast?.confidence_score ??
    status?.confidence_score ??
    selectedFeature?.properties?.confidence ??
    selectedFeature?.properties?.confidence_score ??
    0
  );
  const trendDirection = forecast?.trend_direction || status?.trend_direction || "Stable";

  const { observedSeries, forecastSeries } = useMemo(
    () => buildForecastSeries(selectedFeature, forecast, status),
    [selectedFeature, forecast, status]
  );

  const recommendations = useMemo(() => {
    const seed = Array.isArray(forecast?.recommended_actions) && forecast.recommended_actions.length
      ? forecast.recommended_actions
      : Array.isArray(status?.recommended_actions) && status.recommended_actions.length
        ? status.recommended_actions
        : [];
    const baseline = seed.length
      ? seed
      : normalizeRisk(alertStatus, currentDepth) === "critical"
        ? [
            "Urgent advisory: reduce pumping immediately.",
            "Adopt drip irrigation and schedule extraction.",
            "Install recharge pits and desilt tanks before the dry season."
          ]
        : normalizeRisk(alertStatus, currentDepth) === "warning"
          ? [
              "Monitor pumping closely.",
              "Prioritize recharge pits and water-saving irrigation.",
              "Avoid new high-capacity borewells until levels stabilize."
            ]
          : [
              "Continue monthly monitoring.",
              "Protect existing recharge structures.",
              "Use efficient irrigation to preserve the current balance."
            ];
    return anomalyMatch
      ? ["Inspect the anomaly and compare sensor records.", ...baseline]
      : baseline;
  }, [anomalyMatch, alertStatus, currentDepth, forecast, status]);

  if (!selectedFeature) {
    return (
      <section className="village-action-panel empty">
        <div className="panel-kicker">Prediction + Alerts</div>
        <h3>Select a village</h3>
        <p>Click a village on the map to load forecast months, alerts, and recommended actions.</p>
      </section>
    );
  }

  return (
    <section className="village-action-panel" aria-label="Village prediction and alerts">
      <div className="village-action-header">
        <div>
          <div className="panel-kicker">Prediction + Alerts</div>
          <h3>{villageName}</h3>
          <p>{mandal}, {district}</p>
        </div>
        <div className={`status-pill status-${alertStatus}`}>
          {titleCase(alertStatus)}
        </div>
      </div>

      {loading && <div className="village-action-loading">Loading live forecast and alerts...</div>}
      {error && <div className="village-action-error">{error}</div>}

      {!loading && !error && (
        <>
          <div className="village-action-metrics">
            <div>
              <small>Current Depth</small>
              <strong>{formatDepth(currentDepth)}</strong>
            </div>
            <div>
              <small>Confidence</small>
              <strong>{formatConfidence(confidenceScore)}</strong>
            </div>
            <div>
              <small>Trend</small>
              <strong>{trendDirection}</strong>
            </div>
            <div>
              <small>Anomaly</small>
              <strong>{anomalyMatch ? anomalyMatch.anomaly_type || "Detected" : "None"}</strong>
            </div>
          </div>

          <ForecastLineChart observedSeries={observedSeries} forecastSeries={forecastSeries} />

          <div className="village-forecast-summary">
            <div>
              <small>Past observed</small>
              <strong>{observedSeries.length}</strong>
            </div>
            <div>
              <small>Future months</small>
              <strong>{forecastSeries.length || 3}</strong>
            </div>
            <div>
              <small>Alert level</small>
              <strong className={`status-text status-${alertStatus}`}>{titleCase(alertStatus)}</strong>
            </div>
          </div>

          <div className={`alert-card alert-card-${alertStatus}`}>
            <strong>
              {alertStatus === "critical"
                ? "Critical advisory"
                : alertStatus === "warning"
                  ? "Warning advisory"
                  : "Safe advisory"}
            </strong>
            <p>
              {alertStatus === "critical"
                ? "Groundwater stress is elevated. Reduce pumping immediately and protect recharge structures."
                : alertStatus === "warning"
                  ? "Monitor usage closely and prepare recharge measures before the dry season deepens stress."
                  : "The village is currently stable, but continued monitoring will preserve the present balance."}
            </p>
            {anomalyMatch && (
              <p className="alert-card-note">
                Anomaly score {Number(anomalyMatch.anomaly_score ?? 0).toFixed(2)} detected at {anomalyMatch.detected_at}
              </p>
            )}
          </div>

          <div className="recommendation-card">
            <strong>Recommendations</strong>
            <ul>
              {recommendations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          {forecastSeries.length > 0 && (
            <div className="forecast-table">
              {forecastSeries.map((item) => (
                <div key={`${item.forecast_date}-${item.groundwater_depth}`} className="forecast-table-row">
                  <span>{formatMonthLabel(item.forecast_date)}</span>
                  <strong>{formatDepth(item.groundwater_depth)}</strong>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
