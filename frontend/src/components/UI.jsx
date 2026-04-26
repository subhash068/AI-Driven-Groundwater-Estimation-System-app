import React, { useEffect, useMemo, useRef, useState } from 'react';
import { advisoryLabel } from '../utils/mapUtils';

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

function riskClassName(risk) {
  if (risk === "Critical") return "is-critical";
  if (risk === "Warning") return "is-medium";
  return "is-safe";
}

function formatNumber(value, digits = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "NA";
  return numeric.toFixed(digits);
}

function formatMaybePercent(value, digits = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "NA";
  return `${numeric.toFixed(digits)}%`;
}

function InfoDot({ label, text }) {
  return (
    <span className="info-dot" title={text} aria-label={label}>
      i
    </span>
  );
}

function hasNumericValue(value) {
  return Number.isFinite(Number(value));
}

function interpretSoil(row) {
  if (!row) return [];
  const soil = String(row.soil_taxonomy || row.soil || "").toLowerCase();
  const notes = [];
  if (soil.includes("fine")) notes.push("Fine soils usually store more water and can slow drainage compared with sandy soils.");
  if (soil.includes("clayey")) notes.push("Clayey or clayey-skeletal soils may reduce infiltration but can retain moisture longer.");
  if (soil.includes("skeletal")) notes.push("Skeletal soils contain more rock fragments, so recharge may be uneven across the village.");
  if (soil.includes("paleustalf") || soil.includes("rhodustalf")) notes.push("These upland soils often support agriculture, but recharge depends on texture and structure.");
  if (!notes.length) notes.push("This soil unit affects how quickly rainwater infiltrates, how much moisture is stored, and how crops perform.");
  return notes;
}

function interpretAquifer(row) {
  if (!row) return [];
  const aquifer = String(row.aquifer_type || "").toLowerCase();
  const notes = [];
  if (aquifer.includes("alluv")) notes.push("Alluvial aquifers usually recharge faster and may respond quickly to seasonal recharge and canal seepage.");
  if (aquifer.includes("basalt")) notes.push("Basaltic aquifers often depend on fractures and weathered zones for storage and movement.");
  if (aquifer.includes("granite") || aquifer.includes("gneiss")) notes.push("Hard-rock aquifers generally store water in weathered zones and fractures, so recharge can be limited.");
  if (!notes.length) notes.push("Aquifer type gives a clue about storage, recharge rate, and how quickly groundwater levels may change.");
  return notes;
}

function interpretElevation(row) {
  if (!row) return [];
  const notes = [];
  const source = String(row.elevation_source || "").toLowerCase();
  const elevation = Number(row.elevation);
  const gradient = Number(row.terrain_gradient);
  const isMissing = source.includes("missing_dem") || !hasNumericValue(elevation);
  if (isMissing) {
    notes.push("Elevation data is missing or fallback-only, so no terrain-based interpretation is available yet.");
    return notes;
  }
  if (Number.isFinite(elevation)) notes.push(`Average elevation is ${elevation.toFixed(2)} m, which helps compare the village against nearby recharge zones.`);
  if (Number.isFinite(gradient)) notes.push(`A terrain gradient of ${gradient.toFixed(2)} m suggests how much elevation changes within the village boundary.`);
  if (!notes.length) notes.push("Elevation and terrain gradient help judge runoff, recharge paths, and surface-water accumulation.");
  return notes;
}

function interpretLulc(row) {
  if (!row) return [];
  const notes = [];
  const start = String(row.lulc_start_dominant || "").toLowerCase();
  const end = String(row.lulc_end_dominant || "").toLowerCase();
  const change = Number(row.built_area_change_pct);
  if (start && end && start !== end) notes.push(`Land cover shifted from ${row.lulc_start_dominant} to ${row.lulc_end_dominant}, showing a visible change in village surface use.`);
  if (Number.isFinite(change)) {
    if (change < 0) notes.push(`Built-up area fell by ${Math.abs(change).toFixed(2)}%, which may reduce sealing and improve recharge potential.`);
    if (change > 0) notes.push(`Built-up area rose by ${change.toFixed(2)}%, which can increase runoff and reduce infiltration.`);
  }
  const currentCrops = Number(row.crops_pct);
  const currentWater = Number(row.water_pct);
  if (Number.isFinite(currentCrops) || Number.isFinite(currentWater)) {
    notes.push("Current LULC shares help explain recharge, runoff, and crop pressure in the selected village.");
  }
  if (!notes.length) notes.push("LULC tells us how much land is water, crops, built-up area, bare land, or vegetation, which directly affects recharge.");
  return notes;
}

function buildMeaningCards(row) {
  if (!row) return [];
  return [
    {
      title: "Soil",
      label: row.soil_taxonomy || row.soil || "Unknown",
      notes: interpretSoil(row)
    },
    {
      title: "Aquifer",
      label: row.aquifer_type || "Unknown",
      notes: interpretAquifer(row)
    },
    {
      title: "Elevation",
      label: hasNumericValue(row.elevation) ? `${Number(row.elevation).toFixed(2)} m` : "NA",
      notes: interpretElevation(row)
    },
    {
      title: "LULC",
      label: row.lulc_end_dominant || "Unknown",
      notes: interpretLulc(row)
    }
  ];
}

function buildProfileFields(selectedProfile, selectedRow) {
  if (!selectedProfile) return [];
  const elevationMissing = !hasNumericValue(selectedProfile.elevation) || String(selectedProfile.elevation_source || "").toLowerCase().includes("missing_dem");
  return [
    {
      label: "Village",
      value: selectedProfile.village_name || "Unknown",
      meta: `${selectedProfile.district} / ${selectedProfile.mandal}`
    },
    {
      label: "Soil Class",
      value: selectedProfile.soil_taxonomy || selectedProfile.soil || "Unknown",
      meta: selectedRow?.soil_map_unit || "Soil map unit from source data"
    },
    {
      label: "Aquifer Type",
      value: selectedProfile.aquifer_type || "Unknown",
      meta: "Aquifer classification from source data"
    },
    {
      label: "Elevation",
      value: hasNumericValue(selectedProfile.elevation) ? `${Number(selectedProfile.elevation).toFixed(2)} m` : "NA",
      meta: elevationMissing ? "Missing DEM source" : `Source: ${selectedProfile.elevation_source || "dataset"}`
    },
    {
      label: "Terrain Gradient",
      value: hasNumericValue(selectedProfile.terrain_gradient) ? `${Number(selectedProfile.terrain_gradient).toFixed(2)} m` : "NA",
      meta: "Derived from elevation range"
    },
    {
      label: "Land Cover",
      value: selectedRow?.lulc_end_dominant || "Unknown",
      meta: selectedRow?.lulc_start_dominant ? `Shifted from ${selectedRow.lulc_start_dominant}` : "Current dominant class"
    }
  ];
}

function formatDepth(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "NA";
  return `${numeric.toFixed(2)} m`;
}

function buildTrendDirection(values) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length < 2) return "Stable";
  const delta = finite[finite.length - 1] - finite[0];
  if (delta > 0.5) return "Rising";
  if (delta < -0.5) return "Falling";
  return "Stable";
}

function parseSeriesArray(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => {
      if (entry === null || entry === undefined || entry === "") return null;
      const numeric = Number(entry);
      return Number.isFinite(numeric) ? numeric : null;
    });
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((entry) => {
          if (entry === null || entry === undefined || entry === "") return null;
          const numeric = Number(entry);
          return Number.isFinite(numeric) ? numeric : null;
        });
      }
    } catch {
      return [];
    }
  }
  return [];
}

function parseLabelArray(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => (entry === null || entry === undefined ? "" : String(entry)));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((entry) => (entry === null || entry === undefined ? "" : String(entry)));
      }
    } catch {
      return [];
    }
  }
  return [];
}

function extractYearFromLabel(label, fallbackYear) {
  const match = String(label || "").match(/(20\d{2})/);
  if (match) return Number(match[1]);
  return fallbackYear;
}

function formatTrendLabel(label, index, fallbackStartYear) {
  const text = String(label || "").trim();
  const parsed = new Date(`${text}-01T00:00:00Z`);
  if (!Number.isNaN(parsed.getTime()) && text.length >= 7) {
    return parsed.toLocaleString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
  }
  const year = fallbackStartYear + Math.floor(index / 12);
  return `${MONTH_LABELS[index % 12]} ${year}`;
}

function buildTrendYearOptions(labels, fallbackStartYear = 2023) {
  const safeLabels = Array.isArray(labels) ? labels : [];
  const years = new Set();
  safeLabels.forEach((label, index) => {
    years.add(extractYearFromLabel(label, fallbackStartYear + Math.floor(index / 12)));
  });
  return Array.from(years).sort((a, b) => a - b);
}

function buildYearlyTrendPoints(series, selectedYear, labels = [], fallbackStartYear = 2023) {
  const values = Array.isArray(series) ? series : [];
  const safeLabels = Array.isArray(labels) ? labels : [];
  const year = Number(selectedYear);
  const useLabelYears = safeLabels.length === values.length && safeLabels.some((label) => extractYearFromLabel(label, null) !== null);

  return values
    .map((rawValue, index) => {
      const value = Number(rawValue);
      if (!Number.isFinite(value)) return null;
      if (useLabelYears && Number.isFinite(year)) {
        const labelYear = extractYearFromLabel(safeLabels[index], fallbackStartYear + Math.floor(index / 12));
        if (labelYear !== year) return null;
      } else if (Number.isFinite(year)) {
        const yearOffset = year - fallbackStartYear;
        const startIndex = Math.max(yearOffset * 12, 0);
        if (index < startIndex || index >= startIndex + 12) return null;
      }
      return {
        label: formatTrendLabel(safeLabels[index], index, fallbackStartYear),
        value
      };
    })
    .filter((point) => point && Number.isFinite(point.value));
}

function WaterTrendChart({ points, predictedValue = null, actualLabel = "Actual", predictedLabel = "Predicted" }) {
  const [hoverPoint, setHoverPoint] = useState(null);
  const series = Array.isArray(points)
    ? points
        .map((point, index) => ({
          label: String(point?.label || `Month ${index + 1}`),
          value: Number(point?.value)
        }))
        .filter((point) => Number.isFinite(point.value))
    : [];
  if (!series.length) {
    return <p className="insight-muted">No monthly water-level series available.</p>;
  }

  const width = 100;
  const height = 56;
  const values = series.map((point) => point.value);
  const scaleValues = Number.isFinite(Number(predictedValue))
    ? [...values, Number(predictedValue)]
    : values;
  const min = Math.min(...scaleValues);
  const max = Math.max(...scaleValues);
  const span = Math.max(max - min, 0.5);
  const pathPoints = series.map((point, index) => {
    const x = series.length === 1 ? 6 : (index / (series.length - 1)) * 88 + 6;
    const y = 46 - ((point.value - min) / span) * 34;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  const averageY = 46 - ((average - min) / span) * 34;
  const predictedY = Number.isFinite(Number(predictedValue))
    ? 46 - ((Number(predictedValue) - min) / span) * 34
    : null;

  const hoverLabel = hoverPoint
    ? `${hoverPoint.label}: ${hoverPoint.value.toFixed(2)} m`
    : "Hover a point";

  return (
    <div className="trend-chart-card">
      <div className="trend-chart-wrap">
        <svg viewBox={`0 0 ${width} ${height}`} className="trend-line-chart" role="img" aria-label="Groundwater level graph">
        <defs>
          <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#67e8f9" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#00e5ff" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <line x1="0" y1="8" x2="100" y2="8" className="trend-top-guide" />
        <line x1="0" y1={averageY} x2="100" y2={averageY} className="trend-average-line" />
        {predictedY !== null && (
          <line x1="0" y1={predictedY} x2="100" y2={predictedY} className="trend-predicted-line" />
        )}
        <polygon points={`${pathPoints} 94,46 6,46`} className="trend-area" fill="url(#trendFill)" />
        <polyline points={pathPoints} className="trend-path" />
        {series.map((point, index) => {
          const value = point.value;
          const x = series.length === 1 ? 6 : (index / (series.length - 1)) * 88 + 6;
          const y = 46 - ((value - min) / span) * 34;
          return (
            <circle
              key={`${index}-${value}`}
              cx={x}
              cy={y}
              r="2.6"
              className="trend-point"
              onMouseEnter={() => setHoverPoint({ index, label: point.label, value, x, y })}
              onMouseLeave={() => setHoverPoint(null)}
            />
          );
        })}
        {predictedY !== null && (
          <circle
            cx="94"
            cy={predictedY}
            r="2.6"
            className="trend-predicted-point"
          />
        )}
        </svg>
        {hoverPoint && (
          <div className="trend-tooltip" style={{ left: `${hoverPoint.x}%`, top: `${hoverPoint.y}%` }}>
            <strong>{hoverLabel}</strong>
          </div>
        )}
      </div>
      <div className="trend-legend">
        <span><i className="trend-legend-line" /> {actualLabel}</span>
        <span><i className="trend-legend-average" /> Average</span>
        {Number.isFinite(Number(predictedValue)) && (
          <span><i className="trend-legend-predicted" /> {predictedLabel}</span>
        )}
        <span><i className="trend-legend-point" /> Observed point</span>
      </div>
      <div className="trend-axis-labels" aria-hidden="true">
        {series.map((point, index) => (
          <span key={`${point.label}-${index}`}>{point.label}</span>
        ))}
      </div>
    </div>
  );
}

function DraggableInsightsShellLegacy({ children }) {
  const panelRef = useRef(null);
  const dragStateRef = useRef({ offsetX: 0, offsetY: 0 });
  const resizeStateRef = useRef({ startX: 0, startWidth: 0, startLeft: 0 });
  const hasInitialPosition = useRef(false);
  const [position, setPosition] = useState({ x: 0, y: 96 });
  const [panelWidth, setPanelWidth] = useState(380);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || hasInitialPosition.current) return;
    hasInitialPosition.current = true;
    const initialWidth = Math.min(380, Math.max(window.innerWidth * 0.28, 320));
    setPosition({
      x: Math.max(window.innerWidth - initialWidth - 24, 16),
      y: Math.max(Math.min(96, window.innerHeight - 180), 16)
    });
    setPanelWidth(initialWidth);
  }, []);

  useEffect(() => {
    if ((!isDragging && !isResizing) || typeof window === "undefined") return undefined;

    const handlePointerMove = (event) => {
      const panel = panelRef.current;
      if (!panel) return;
      const rect = panel.getBoundingClientRect();
      if (isDragging) {
        const nextX = event.clientX - dragStateRef.current.offsetX;
        const nextY = event.clientY - dragStateRef.current.offsetY;
        const maxX = Math.max(window.innerWidth - rect.width - 12, 12);
        const maxY = Math.max(window.innerHeight - rect.height - 12, 12);
        setPosition({
          x: Math.min(Math.max(nextX, 12), maxX),
          y: Math.min(Math.max(nextY, 12), maxY)
        });
      }
      if (isResizing) {
        const minWidth = 300;
        const nextWidth = Math.max(
          minWidth,
          resizeStateRef.current.startWidth + (resizeStateRef.current.startX - event.clientX)
        );
        const maxWidth = Math.max(window.innerWidth - position.x - 12, minWidth);
        const clampedWidth = Math.min(nextWidth, maxWidth);
        const nextX = resizeStateRef.current.startLeft + (resizeStateRef.current.startWidth - clampedWidth);
        setPanelWidth(clampedWidth);
        setPosition((prev) => ({
          ...prev,
          x: Math.min(Math.max(nextX, 12), Math.max(window.innerWidth - clampedWidth - 12, 12))
        }));
      }
    };

    const handlePointerUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, [isDragging, isResizing, position.x]);

  const beginDrag = (event) => {
    if (typeof window === "undefined" || event.button !== 0 || isResizing) return;
    const panel = panelRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    dragStateRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top
    };
    setIsDragging(true);
    event.preventDefault();
  };

  const beginResize = (event) => {
    if (typeof window === "undefined" || event.button !== 0 || isDragging) return;
    const panel = panelRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    resizeStateRef.current = {
      startX: event.clientX,
      startWidth: rect.width,
      startLeft: rect.left
    };
    setIsResizing(true);
    event.preventDefault();
    event.stopPropagation();
  };

  const resetPosition = () => {
    if (typeof window === "undefined") return;
    const initialWidth = Math.min(380, Math.max(window.innerWidth * 0.28, 320));
    setPosition({
      x: Math.max(window.innerWidth - initialWidth - 24, 16),
      y: 96
    });
    setPanelWidth(initialWidth);
  };

  return (
    <aside
      ref={panelRef}
      className="insights-panel"
      style={{ left: `${position.x}px`, top: `${position.y}px`, width: `${panelWidth}px` }}
    >


      {children}
    </aside>
  );
}

function DraggableInsightsShell({ children }) {
  const panelRef = useRef(null);
  const dragStateRef = useRef({ offsetX: 0, offsetY: 0 });
  const resizeStateRef = useRef({ startX: 0, startWidth: 0, startLeft: 0 });
  const hasInitialPosition = useRef(false);
  const [position, setPosition] = useState({ x: 0, y: 96 });
  const [panelWidth, setPanelWidth] = useState(380);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || hasInitialPosition.current) return;
    hasInitialPosition.current = true;
    const initialWidth = Math.min(380, Math.max(window.innerWidth * 0.28, 320));
    setPosition({
      x: Math.max(window.innerWidth - initialWidth - 24, 16),
      y: Math.max(Math.min(96, window.innerHeight - 180), 16)
    });
    setPanelWidth(initialWidth);
  }, []);

  useEffect(() => {
    if ((!isDragging && !isResizing) || typeof window === "undefined") return undefined;

    const handlePointerMove = (event) => {
      const panel = panelRef.current;
      if (!panel) return;
      const rect = panel.getBoundingClientRect();
      if (isDragging) {
        const nextX = event.clientX - dragStateRef.current.offsetX;
        const nextY = event.clientY - dragStateRef.current.offsetY;
        const maxX = Math.max(window.innerWidth - rect.width - 12, 12);
        const maxY = Math.max(window.innerHeight - rect.height - 12, 12);
        setPosition({
          x: Math.min(Math.max(nextX, 12), maxX),
          y: Math.min(Math.max(nextY, 12), maxY)
        });
      }
      if (isResizing) {
        const minWidth = 300;
        const nextWidth = Math.max(
          minWidth,
          resizeStateRef.current.startWidth + (resizeStateRef.current.startX - event.clientX)
        );
        const maxWidth = Math.max(window.innerWidth - position.x - 12, minWidth);
        const clampedWidth = Math.min(nextWidth, maxWidth);
        const nextX = resizeStateRef.current.startLeft + (resizeStateRef.current.startWidth - clampedWidth);
        setPanelWidth(clampedWidth);
        setPosition((prev) => ({
          ...prev,
          x: Math.min(Math.max(nextX, 12), Math.max(window.innerWidth - clampedWidth - 12, 12))
        }));
      }
    };

    const handlePointerUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, [isDragging, isResizing, position.x]);

  const beginDrag = (event) => {
    if (typeof window === "undefined" || event.button !== 0 || isResizing) return;
    const panel = panelRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    dragStateRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top
    };
    setIsDragging(true);
    event.preventDefault();
  };

  const beginResize = (event) => {
    if (typeof window === "undefined" || event.button !== 0 || isDragging) return;
    const panel = panelRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    resizeStateRef.current = {
      startX: event.clientX,
      startWidth: rect.width,
      startLeft: rect.left
    };
    setIsResizing(true);
    event.preventDefault();
    event.stopPropagation();
  };

  const resetPosition = () => {
    if (typeof window === "undefined") return;
    const initialWidth = Math.min(380, Math.max(window.innerWidth * 0.28, 320));
    setPosition({
      x: Math.max(window.innerWidth - initialWidth - 24, 16),
      y: 96
    });
    setPanelWidth(initialWidth);
  };

  return (
    <aside
      ref={panelRef}
      className="insights-panel"
      style={{ left: `${position.x}px`, top: `${position.y}px`, width: `${panelWidth}px` }}
    >


      {children}
    </aside>
  );
}

function ChartCard({ title, subtitle, children }) {
  return (
    <section className="insight-chart-card">
      <div className="insight-section-heading">
        <small>{title}</small>
        <span>{subtitle}</span>
      </div>
      {children}
    </section>
  );
}

function LulcBarChart({ data }) {
  const bars = Array.isArray(data) ? data : [];
  const max = Math.max(...bars.map((item) => Number(item.value) || 0), 1);
  return (
    <div className="lulc-bar-chart">
      {bars.map((item) => (
        <div key={item.key || item.label} className="lulc-bar-item">
          <div className="lulc-bar-track">
            <div
              className="lulc-bar-fill"
              style={{
                height: `${((Number(item.value) || 0) / max) * 100}%`,
                background: item.color || "#38BDF8"
              }}
            />
          </div>
          <strong>{item.label}</strong>
          <span>{formatNumber(item.value, 1)}%</span>
        </div>
      ))}
    </div>
  );
}

function DonutChart({ data, centerTitle, centerValue, centerSubtitle }) {
  const segments = Array.isArray(data) ? data.filter((item) => Number(item.value) > 0) : [];
  const total = segments.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
  let cursor = 0;
  const gradient = segments.length
    ? segments
        .map((item) => {
          const start = cursor;
          cursor += (Number(item.value || 0) / total) * 100;
          return `${item.color || "#64748B"} ${start}% ${cursor}%`;
        })
        .join(", ")
    : "rgba(148, 163, 184, 0.2) 0% 100%";

  return (
    <div className="donut-panel">
      <div className="donut-chart" style={{ background: `conic-gradient(${gradient})` }}>
        <div className="donut-hole">
          <strong>{centerTitle}</strong>
          <span>{centerValue}</span>
          <small>{centerSubtitle}</small>
        </div>
      </div>
      <div className="donut-legend">
        {segments.map((item) => (
          <div key={item.key || item.label} className="donut-legend-item">
            <span className="donut-swatch" style={{ background: item.color || "#64748B" }} />
            <div>
              <strong>{item.label}</strong>
              <span>{formatNumber(item.value, 1)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ComparisonChart({ data }) {
  const rows = Array.isArray(data) ? data : [];
  const max = Math.max(
    ...rows.flatMap((item) => [Number(item.baseline) || 0, Number(item.current) || 0]),
    1
  );
  return (
    <div className="comparison-chart">
      {rows.map((item) => (
        <div key={item.key || item.label} className="comparison-row">
          <div className="comparison-label">
            <strong>{item.label}</strong>
            <span>{formatNumber(item.delta, 2)}% change</span>
          </div>
          <div className="comparison-bars" aria-hidden="true">
            <span
              className="comparison-bar baseline"
              style={{ width: `${((Number(item.baseline) || 0) / max) * 100}%` }}
            />
            <span
              className="comparison-bar current"
              style={{ width: `${((Number(item.current) || 0) / max) * 100}%` }}
            />
          </div>
          <div className="comparison-values">
            <span>2011 {formatNumber(item.baseline, 1)}%</span>
            <span>2021 {formatNumber(item.current, 1)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SummaryBars({ data }) {
  const rows = Array.isArray(data) ? data : [];
  return (
    <div className="summary-bar-list">
      {rows.map((item) => (
        <div key={item.key} className="summary-bar-row">
          <div className="summary-bar-head">
            <strong>{item.label}</strong>
            <span>{formatNumber(item.value, item.key === "gw_level" ? 2 : 1)}{item.unit ? ` ${item.unit}` : ""}</span>
          </div>
          <div className="summary-bar-track">
            <div className="summary-bar-fill" style={{ width: `${item.percent}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DashboardTopBar({
  monthIndex,
  setMonthIndex,
  aiPredictionEnabled,
  setAiPredictionEnabled,
  stats,
  isFullDashboardOpen,
  onToggleFullDashboard,
  scopeLabel
}) {
  const year = 2023 + Math.floor(monthIndex / 12);
  const month = MONTH_LABELS[monthIndex % 12];
  const titleScope = scopeLabel || "All Villages";

  return (
    <div className="dashboard-top-bar dashboard-top-bar-main">
      <div className="topbar-title topbar-title-main">
        <span className="topbar-kicker">Dashboard</span>
        <strong>{titleScope}</strong>
        <span>{month} {year}</span>
      </div>
      <div className="topbar-center-controls">
        <div className="topbar-time topbar-time-main">
          <label htmlFor="year-slider">Year-wise timeline</label>
          <input
            id="year-slider"
            type="range"
            min="0"
            max="23"
            value={monthIndex}
            onChange={(event) => setMonthIndex(Number(event.target.value))}
          />
        </div>
        <label className="ai-toggle ai-toggle-main">
          <input
            type="checkbox"
            checked={aiPredictionEnabled}
            onChange={() => setAiPredictionEnabled(!aiPredictionEnabled)}
          />
          <span>AI Prediction {aiPredictionEnabled ? "ON" : "OFF"}</span>
        </label>
      </div>
      <div className="topbar-actions">
        <button type="button" className="dashboard-toggle dashboard-toggle-main" onClick={onToggleFullDashboard}>
          {isFullDashboardOpen ? "Close Dashboard" : "Open Dashboard"}
        </button>
        <div className="topbar-stats topbar-stats-main">
          <div>
            <small>Safe</small>
            <strong>{stats.safe}</strong>
          </div>
          <div>
            <small>Warning</small>
            <strong>{stats.warning}</strong>
          </div>
          <div>
            <small>Critical</small>
            <strong>{stats.critical}</strong>
          </div>
        </div>
      </div>
    </div>
  );
}

export function MapLegend({
  showGroundwaterLevels = true,
  showPiezometers = false,
  showWells = false,
  showAnomalies = false,
  districtNote = null
}) {
  return (
    <div className="map-legend">
      {showGroundwaterLevels ? (
        <>
          <div className="legend-item">
            <div className="legend-color" style={{ background: '#22C55E' }}></div>
            <span>High Groundwater</span>
          </div>
          <div className="legend-item">
            <div className="legend-color" style={{ background: '#FACC15' }}></div>
            <span>Medium Groundwater</span>
          </div>
          <div className="legend-item">
            <div className="legend-color" style={{ background: '#EF4444' }}></div>
            <span>Low Groundwater</span>
          </div>
        </>
      ) : (
        <div className="legend-item">
          <div className="legend-color" style={{ background: '#64748B' }}></div>
          <span>Groundwater Levels hidden</span>
        </div>
      )}
      {showPiezometers && (
        <>
          <div className="legend-divider" />
          <div className="legend-item">
            <div className="legend-color" style={{ background: 'linear-gradient(90deg, #ef4444 0%, #3b82f6 100%)' }}></div>
            <span>Piezometers: low to high depth</span>
          </div>
        </>
      )}
      {showWells && (
        <>
          <div className="legend-divider" />
          <div className="legend-item">
            <div className="legend-color" style={{ background: '#38BDF8' }}></div>
            <span>Wells: extraction infrastructure</span>
          </div>
        </>
      )}
      {showAnomalies && (
        <>
          <div className="legend-divider" />
          <div className="legend-item">
            <div className="legend-color" style={{ background: 'linear-gradient(90deg, #3B82F6 0%, #FACC15 35%, #F59E0B 70%, #EF4444 100%)' }}></div>
            <span>Anomalies: rise to severe drop</span>
          </div>
        </>
      )}
      {districtNote && (
        <>
          <div className="legend-divider" />
          <div className="legend-item">
            <div className="legend-color" style={{ background: '#E2E8F0' }}></div>
            <span>{districtNote}</span>
          </div>
        </>
      )}
    </div>
  );
}

function VillageInsightsPanelContent(props) {
  return <VillageInsightsPanelContentImpl {...props} />;
}

export function VillageInsightsPanel({
  selectedFeature,
  monthIndex,
  aiPredictionEnabled,
  aquiferAnalytics
}) {
  if (!selectedFeature) {
    return (
      <DraggableInsightsShell>
        <h2>Village Insights</h2>
        <p className="insight-muted">
          Click any village on the map to view groundwater level, trend, risk status, and recharge suggestion.
        </p>
        {aquiferAnalytics && (
          <div className="insight-aquifer">
            <small>Aquifer Analytics</small>
            <div className="insight-metric-grid">
              <div>
                <small>Units Loaded</small>
                <strong>{aquiferAnalytics.totalPolygons}</strong>
              </div>
              <div>
                <small>Total Aquifer Area</small>
                <strong>{aquiferAnalytics.totalAreaKm2.toFixed(2)} km²</strong>
              </div>
              <div>
                <small>Dominant Aquifer Class</small>
                <strong>{aquiferAnalytics.dominantClass?.name || "NA"}</strong>
              </div>
              <div>
                <small>Active Filter Dominant</small>
                <strong>{aquiferAnalytics.filteredVillageDominantAquifer?.name || "NA"}</strong>
              </div>
            </div>
          </div>
        )} 
      </DraggableInsightsShell>
    );
  }

  const props = selectedFeature.properties || {};
  const isSampleVillage = String(props.village_name || "").trim().toLowerCase() === "sample village";
  if (isSampleVillage) {
    return (
      <DraggableInsightsShell>
        <h2>Village Insights</h2>
        <p className="insight-muted">
          Sample placeholder record removed from insights. Click a real village polygon on the map to view details.
        </p>
      </DraggableInsightsShell>
    );
  }

  return (
    <VillageInsightsPanelContent
      selectedFeature={selectedFeature}
      monthIndex={monthIndex}
      aiPredictionEnabled={aiPredictionEnabled}
      aquiferAnalytics={aquiferAnalytics}
    />
  );

  const monthlyDepths = useMemo(
    () => parseSeriesArray(props.monthly_depths),
    [props.monthly_depths]
  );
  const monthlyDepthsFull = useMemo(
    () => parseSeriesArray(props.monthly_depths_full ?? props.monthly_depths_history),
    [props.monthly_depths_full, props.monthly_depths_history]
  );
  const monthlyDepthDates = useMemo(
    () => parseLabelArray(props.monthly_depths_full_dates ?? props.monthly_depths_dates),
    [props.monthly_depths_full_dates, props.monthly_depths_dates]
  );
  const trendYearOptions = useMemo(
    () => buildTrendYearOptions(monthlyDepthDates, 1998),
    [monthlyDepthDates]
  );
  const defaultTrendYear = useMemo(
    () => trendYearOptions[trendYearOptions.length - 1] || (1998 + Math.floor(monthIndex / 12)),
    [trendYearOptions, monthIndex]
  );
  const [trendYear, setTrendYear] = useState(defaultTrendYear);
  const backendDepth = Number(props.current_depth);
  const actualLastMonth = Number.isFinite(Number(props.actual_last_month))
    ? Number(props.actual_last_month)
    : Number.isFinite(Number(props.target_last_month))
      ? Number(props.target_last_month)
      : monthlyDepthsFull.slice().reverse().find((value) => Number.isFinite(Number(value))) ?? null;
  const depthFromMonthly = monthlyDepths[monthIndex];
  const depthFromSingle = props.depth;
  const currentDepth = Number.isFinite(Number(actualLastMonth))
    ? Number(actualLastMonth)
    : Number.isFinite(backendDepth)
      ? backendDepth
    : Number.isFinite(Number(depthFromMonthly))
      ? Number(depthFromMonthly)
      : Number.isFinite(Number(depthFromSingle))
        ? Number(depthFromSingle)
        : null;
  const predictedDepth = Number.isFinite(Number(props.predicted_groundwater_level))
    ? Number(props.predicted_groundwater_level)
    : null;
  const depthDifference = currentDepth !== null && predictedDepth !== null
    ? Number((currentDepth - predictedDepth).toFixed(2))
    : null;
  const depthError = depthDifference !== null ? Math.abs(depthDifference) : null;
  const depthErrorBadge = depthError === null
    ? { label: "Unknown", className: "error-unknown" }
    : depthError <= 0.5
      ? { label: "Low error", className: "error-low" }
      : depthError <= 1.5
        ? { label: "Moderate error", className: "error-medium" }
        : { label: "High error", className: "error-high" };
  const risk = currentDepth !== null ? advisoryLabel(currentDepth) : null;
  useEffect(() => {
    setTrendYear(defaultTrendYear);
  }, [defaultTrendYear, props.village_id, props.village_name]);
  const safeTrendYear = trendYearOptions.includes(trendYear)
    ? trendYear
    : defaultTrendYear;
  const trendSourceSeries = monthlyDepthsFull.length ? monthlyDepthsFull : monthlyDepths;
  const trendSourceLabels = monthlyDepthDates.length ? monthlyDepthDates : [];
  const trendPoints = buildYearlyTrendPoints(trendSourceSeries, safeTrendYear, trendSourceLabels, 1998);
  const trendValues = trendPoints.map((point) => point.value);
  const trendDirection = buildTrendDirection(trendValues);
  const trendAverage = trendValues.length
    ? Number((trendValues.reduce((sum, value) => sum + value, 0) / trendValues.length).toFixed(2))
    : null;
  const groundwaterHistory = useMemo(() => {
    const values = monthlyDepthsFull.length ? monthlyDepthsFull : monthlyDepths;
    const labels = monthlyDepthDates.length ? monthlyDepthDates : values.map((_, index) => `Month ${index + 1}`);
    const actualSeries = labels.map((label, index) => {
      const depth = Number(values[index]);
      return {
        date: String(label || ""),
        depth: Number.isFinite(depth) ? depth : null
      };
    });
    return {
      actual_series: actualSeries,
      available_years: trendYearOptions
    };
  }, [monthlyDepthsFull, monthlyDepths, monthlyDepthDates, trendYearOptions]);
  const groundwaterInsights = useMemo(() => ({
    predicted_gwl: predictedDepth,
    actual_last_month: actualLastMonth,
    error: depthDifference,
    obs_station_count: Number(props.obs_station_count ?? 0),
    trend_slope: Number.isFinite(Number(props.trend_slope)) ? Number(props.trend_slope) : null,
  }), [predictedDepth, actualLastMonth, depthDifference, props.obs_station_count, props.trend_slope]);
  const groundwaterHistoryLoading = false;
  const groundwaterHistoryError = null;
  const [groundwaterYear, setGroundwaterYear] = useState(defaultTrendYear);

  useEffect(() => {
    setGroundwaterYear(defaultTrendYear);
  }, [defaultTrendYear, props.village_id]);

  const groundwaterPoints = (groundwaterHistory?.actual_series || [])
    .map((point) => ({
      label: String(point?.date || ""),
      value: Number(point?.depth),
    }))
    .filter((point) => Number.isFinite(point.value))
    .filter((point) => !Number.isFinite(Number(groundwaterYear)) || point.label.startsWith(`${Number(groundwaterYear)}-`));
  const groundwaterPredicted = Number.isFinite(Number(groundwaterInsights?.predicted_gwl))
    ? Number(groundwaterInsights.predicted_gwl)
    : predictedDepth;
  const groundwaterActualLast = Number.isFinite(Number(groundwaterInsights?.actual_last_month))
    ? Number(groundwaterInsights.actual_last_month)
    : actualLastMonth;
  const groundwaterError = Number.isFinite(Number(groundwaterInsights?.error))
    ? Number(groundwaterInsights.error)
    : depthDifference;

  let rechargeSuggestion = "No groundwater data available for this village.";
  if (currentDepth !== null) {
    rechargeSuggestion = "Maintain current extraction and protect village recharge structures.";
    if (risk === "Warning") {
      rechargeSuggestion = "Adopt staggered pumping and prioritize farm-pond recharge before peak summer.";
    }
    if (risk === "Critical") {
      rechargeSuggestion = "Restrict borewell extraction and activate artificial recharge interventions immediately.";
    }
  }

  return (
    <DraggableInsightsShell>
      <h2>Village Insights</h2>
      <div className="insight-location">
        <strong>{props.village_name || "Selected Village"}</strong>
        <span>{props.mandal || "Mandal"}, {props.district || "District"}</span>
      </div>

      <div className="insight-metric-grid">
        <div>
          <small>Actual Groundwater</small>
          <strong>{formatDepth(currentDepth)}</strong>
        </div>
        <div>
          <small>Risk Status</small>
          <strong className={currentDepth !== null ? riskClassName(risk) : ""}>{currentDepth !== null ? risk : "NA"}</strong>
        </div>
        <div>
          <small>Total Wells</small>
          <strong>{Number(props.wells_total || 0).toFixed(0)}</strong>
        </div>
        <div>
          <small>Functioning Pump Wells</small>
          <strong>{Number(props.pumping_functioning_wells || 0).toFixed(0)}</strong>
        </div>
        <div>
          <small>Avg Bore Depth</small>
          <strong>{Number(props.avg_bore_depth_m || 0) > 0 ? `${Number(props.avg_bore_depth_m).toFixed(2)} m` : "NA"}</strong>
        </div>
        <div>
          <small>Irrigation</small>
          <strong>{props.dominant_irrigation || "Unknown"}</strong>
        </div>
      </div>

      <div className="insight-comparison">
        <div className="insight-section-heading">
          <small>Actual vs Predicted</small>
          <span>{predictedDepth !== null ? "Model validation" : "Prediction unavailable"}</span>
        </div>
        <div className="insight-comparison-grid">
          <div className="comparison-card actual">
            <small>Actual</small>
            <strong>{formatDepth(currentDepth)}</strong>
          </div>
          <div className="comparison-card predicted">
            <small>Predicted</small>
            <strong>{formatDepth(predictedDepth)}</strong>
          </div>
          <div className={`comparison-card delta ${depthDifference === null ? "" : depthDifference > 0 ? "is-critical" : depthDifference < 0 ? "is-safe" : ""}`}>
            <small>Difference</small>
            <strong>
              {depthDifference === null
                ? "NA"
                : `${depthDifference > 0 ? "+" : ""}${depthDifference.toFixed(2)} m`}
            </strong>
          </div>
          <div className="comparison-card meta">
            <small>Trend</small>
            <strong>{trendDirection}</strong>
          </div>
        </div>
        <div className={`error-badge ${depthErrorBadge.className}`}>
          <span>{depthErrorBadge.label}</span>
          <strong>{depthError !== null ? `${depthError.toFixed(2)} m error` : "No comparison yet"}</strong>
        </div>
        <p className="insight-muted" style={{ marginTop: '8px' }}>
          Positive difference means the observed water table is deeper than the model estimate.
        </p>
      </div>

      <div className="insight-trend">
        <div className="insight-section-heading" style={{ marginBottom: '8px' }}>
          <small>Groundwater Level Graph</small>
          <label
            htmlFor="trend-year-filter"
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <span>Year</span>
            <select
              id="trend-year-filter"
              value={safeTrendYear}
              onChange={(event) => setTrendYear(Number(event.target.value))}
            >
              {trendYearOptions.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </label>
        </div>
        <WaterTrendChart points={trendPoints} predictedValue={predictedDepth} actualLabel="Actual" predictedLabel="Predicted" />
        <p className="insight-muted" style={{ marginTop: '8px' }}>
          Average: {trendAverage !== null ? `${trendAverage.toFixed(2)} m` : "NA"} · Direction: {trendDirection}
        </p>
      </div>

      <div className="insight-trend">
        <div className="insight-section-heading" style={{ marginBottom: '8px' }}>
          <small>Groundwater History</small>
          <label
            htmlFor="history-year-filter"
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <span>Year</span>
            <select
              id="history-year-filter"
              value={Number.isFinite(Number(groundwaterYear)) ? groundwaterYear : ""}
              onChange={(event) => setGroundwaterYear(Number(event.target.value))}
            >
              {(groundwaterHistory?.available_years?.length ? groundwaterHistory.available_years : trendYearOptions).map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </label>
        </div>
        {groundwaterHistoryLoading && <p className="insight-muted">Loading groundwater history...</p>}
        {!groundwaterHistoryLoading && (
          <>
            <WaterTrendChart points={groundwaterPoints} predictedValue={groundwaterPredicted} actualLabel="Actual" predictedLabel="Predicted" />
            <div className="insight-comparison-grid" style={{ marginTop: '8px' }}>
              <div className="comparison-card actual">
                <small>Actual Last Month</small>
                <strong>{formatDepth(groundwaterActualLast)}</strong>
              </div>
              <div className="comparison-card predicted">
                <small>Prediction Error</small>
                <strong>{Number.isFinite(groundwaterError) ? `${groundwaterError > 0 ? "+" : ""}${groundwaterError.toFixed(2)} m` : "NA"}</strong>
              </div>
              <div className="comparison-card meta">
                <small>Stations</small>
                <strong>{Number(groundwaterInsights?.obs_station_count ?? props.obs_station_count ?? 0).toFixed(0)}</strong>
              </div>
              <div className="comparison-card meta">
                <small>Trend Slope</small>
                <strong>{Number.isFinite(Number(groundwaterInsights?.trend_slope ?? props.trend_slope)) ? Number(groundwaterInsights?.trend_slope ?? props.trend_slope).toFixed(4) : "NA"}</strong>
              </div>
            </div>
          </>
        )}
        {groundwaterHistoryError && (
          <p className="insight-muted" style={{ marginTop: '8px' }}>
            {groundwaterHistoryError}
          </p>
        )}
      </div>

      <div className="insight-recharge">
        <small>Recharge Suggestion</small>
        <p>{rechargeSuggestion}</p>
      </div>

      {aquiferAnalytics && (
        <div className="insight-aquifer">
          <small>Aquifer Analytics</small>
          <div className="insight-metric-grid">
            <div>
              <small>Units Loaded</small>
              <strong>{aquiferAnalytics.totalPolygons}</strong>
            </div>
            <div>
              <small>Total Aquifer Area</small>
              <strong>{aquiferAnalytics.totalAreaKm2.toFixed(2)} km²</strong>
            </div>
            <div>
              <small>Dominant Aquifer Class</small>
              <strong>{aquiferAnalytics.dominantClass?.name || "NA"}</strong>
            </div>
            <div>
              <small>Selected Village Aquifer</small>
              <strong>{aquiferAnalytics.selectedVillageAquifer?.name || "No overlap"}</strong>
            </div>
          </div>
          {aquiferAnalytics.filteredVillageDominantAquifer && (
            <p className="insight-muted" style={{ marginTop: '8px' }}>
              Active filter dominant aquifer: {aquiferAnalytics.filteredVillageDominantAquifer.name} (
              {aquiferAnalytics.filteredVillageDominantAquifer.villageCount} villages)
            </p>
          )}
        </div>
      )}

      <p className="insight-muted">
        AI Prediction: {aiPredictionEnabled ? "Enabled" : "Disabled"}.
      </p>
    </DraggableInsightsShell>
  );
}

export const VillageInsightsPanelV2 = VillageInsightsPanel;

function VillageInsightsPanelContentImpl({
  selectedFeature,
  monthIndex,
  aiPredictionEnabled,
  aquiferAnalytics
}) {
  const props = selectedFeature?.properties || {};
  const monthlyDepths = useMemo(() => parseSeriesArray(props.monthly_depths), [props.monthly_depths]);
  const monthlyDepthsFull = useMemo(
    () => parseSeriesArray(props.monthly_depths_full ?? props.monthly_depths_history),
    [props.monthly_depths_full, props.monthly_depths_history]
  );
  const monthlyDepthDates = useMemo(
    () => parseLabelArray(props.monthly_depths_full_dates ?? props.monthly_depths_dates),
    [props.monthly_depths_full_dates, props.monthly_depths_dates]
  );
  const trendYearOptions = useMemo(
    () => buildTrendYearOptions(monthlyDepthDates, 1998),
    [monthlyDepthDates]
  );
  const defaultTrendYear = useMemo(
    () => trendYearOptions[trendYearOptions.length - 1] || (1998 + Math.floor(monthIndex / 12)),
    [trendYearOptions, monthIndex]
  );
  const [trendYear, setTrendYear] = useState(defaultTrendYear);
  const backendDepth = Number(props.current_depth);
  const actualLastMonth = Number.isFinite(Number(props.actual_last_month))
    ? Number(props.actual_last_month)
    : Number.isFinite(Number(props.target_last_month))
      ? Number(props.target_last_month)
      : monthlyDepthsFull.slice().reverse().find((value) => Number.isFinite(Number(value))) ?? null;
  const depthFromMonthly = monthlyDepths[monthIndex];
  const depthFromSingle = props.depth;
  const currentDepth = Number.isFinite(Number(actualLastMonth))
    ? Number(actualLastMonth)
    : Number.isFinite(backendDepth)
      ? backendDepth
      : Number.isFinite(Number(depthFromMonthly))
        ? Number(depthFromMonthly)
        : Number.isFinite(Number(depthFromSingle))
          ? Number(depthFromSingle)
          : null;
  const predictedDepth = Number.isFinite(Number(props.predicted_groundwater_level))
    ? Number(props.predicted_groundwater_level)
    : null;
  const depthDifference = currentDepth !== null && predictedDepth !== null
    ? Number((currentDepth - predictedDepth).toFixed(2))
    : null;
  const depthError = depthDifference !== null ? Math.abs(depthDifference) : null;
  const depthErrorBadge = depthError === null
    ? { label: "Unknown", className: "error-unknown" }
    : depthError <= 0.5
      ? { label: "Low error", className: "error-low" }
      : depthError <= 1.5
        ? { label: "Moderate error", className: "error-medium" }
        : { label: "High error", className: "error-high" };
  const risk = currentDepth !== null ? advisoryLabel(currentDepth) : null;

  useEffect(() => {
    setTrendYear(defaultTrendYear);
  }, [defaultTrendYear, props.village_id, props.village_name]);

  const safeTrendYear = trendYearOptions.includes(trendYear) ? trendYear : defaultTrendYear;
  const trendSourceSeries = monthlyDepthsFull.length ? monthlyDepthsFull : monthlyDepths;
  const trendSourceLabels = monthlyDepthDates.length ? monthlyDepthDates : [];
  const trendPoints = buildYearlyTrendPoints(trendSourceSeries, safeTrendYear, trendSourceLabels, 1998);
  const trendValues = trendPoints.map((point) => point.value);
  const trendDirection = buildTrendDirection(trendValues);
  const trendAverage = trendValues.length
    ? Number((trendValues.reduce((sum, value) => sum + value, 0) / trendValues.length).toFixed(2))
    : null;
  const groundwaterHistory = useMemo(() => {
    const values = monthlyDepthsFull.length ? monthlyDepthsFull : monthlyDepths;
    const labels = monthlyDepthDates.length ? monthlyDepthDates : values.map((_, index) => `Month ${index + 1}`);
    const actualSeries = labels.map((label, index) => {
      const depth = Number(values[index]);
      return {
        date: String(label || ""),
        depth: Number.isFinite(depth) ? depth : null
      };
    });
    return {
      actual_series: actualSeries,
      available_years: trendYearOptions
    };
  }, [monthlyDepthsFull, monthlyDepths, monthlyDepthDates, trendYearOptions]);
  const groundwaterInsights = useMemo(() => ({
    predicted_gwl: predictedDepth,
    actual_last_month: actualLastMonth,
    error: depthDifference,
    obs_station_count: Number(props.obs_station_count ?? 0),
    trend_slope: Number.isFinite(Number(props.trend_slope)) ? Number(props.trend_slope) : null,
  }), [predictedDepth, actualLastMonth, depthDifference, props.obs_station_count, props.trend_slope]);
  const groundwaterHistoryLoading = false;
  const groundwaterHistoryError = null;
  const [groundwaterYear, setGroundwaterYear] = useState(defaultTrendYear);

  useEffect(() => {
    setGroundwaterYear(defaultTrendYear);
  }, [defaultTrendYear, props.village_id]);

  const groundwaterPoints = (groundwaterHistory?.actual_series || [])
    .map((point) => ({
      label: String(point?.date || ""),
      value: Number(point?.depth),
    }))
    .filter((point) => Number.isFinite(point.value))
    .filter((point) => !Number.isFinite(Number(groundwaterYear)) || point.label.startsWith(`${Number(groundwaterYear)}-`));
  const groundwaterPredicted = Number.isFinite(Number(groundwaterInsights?.predicted_gwl))
    ? Number(groundwaterInsights.predicted_gwl)
    : predictedDepth;
  const groundwaterActualLast = Number.isFinite(Number(groundwaterInsights?.actual_last_month))
    ? Number(groundwaterInsights.actual_last_month)
    : actualLastMonth;
  const groundwaterError = Number.isFinite(Number(groundwaterInsights?.error))
    ? Number(groundwaterInsights.error)
    : depthDifference;

  let rechargeSuggestion = "No groundwater data available for this village.";
  if (currentDepth !== null) {
    rechargeSuggestion = "Maintain current extraction and protect village recharge structures.";
    if (risk === "Warning") {
      rechargeSuggestion = "Adopt staggered pumping and prioritize farm-pond recharge before peak summer.";
    }
    if (risk === "Critical") {
      rechargeSuggestion = "Restrict borewell extraction and activate artificial recharge interventions immediately.";
    }
  }

  return (
    <DraggableInsightsShell>
      <h2>Village Insights</h2>
      <div className="insight-location">
        <strong>{props.village_name || "Selected Village"}</strong>
        <span>{props.mandal || "Mandal"}, {props.district || "District"}</span>
      </div>
      <div className="insight-metric-grid">
        <div>
          <small>Actual Groundwater</small>
          <strong>{formatDepth(currentDepth)}</strong>
        </div>
        <div>
          <small>Risk Status</small>
          <strong className={currentDepth !== null ? riskClassName(risk) : ""}>{currentDepth !== null ? risk : "NA"}</strong>
        </div>
        <div>
          <small>Total Wells</small>
          <strong>{Number(props.wells_total || 0).toFixed(0)}</strong>
        </div>
        <div>
          <small>Functioning Pump Wells</small>
          <strong>{Number(props.pumping_functioning_wells || 0).toFixed(0)}</strong>
        </div>
        <div>
          <small>Avg Bore Depth</small>
          <strong>{Number(props.avg_bore_depth_m || 0) > 0 ? `${Number(props.avg_bore_depth_m).toFixed(2)} m` : "NA"}</strong>
        </div>
        <div>
          <small>Irrigation</small>
          <strong>{props.dominant_irrigation || "Unknown"}</strong>
        </div>
      </div>
      <div className="insight-comparison">
        <div className="insight-section-heading">
          <small>Actual vs Predicted</small>
          <span>{predictedDepth !== null ? "Model validation" : "Prediction unavailable"}</span>
        </div>
        <div className="insight-comparison-grid">
          <div className="comparison-card actual">
            <small>Actual Depth</small>
            <strong>{formatDepth(currentDepth)}</strong>
          </div>
          <div className="comparison-card predicted">
            <small>Predicted Depth</small>
            <strong>{formatDepth(predictedDepth)}</strong>
          </div>
          <div className="comparison-card meta">
            <small>Prediction Error</small>
            <strong>{Number.isFinite(depthDifference) ? `${depthDifference > 0 ? "+" : ""}${depthDifference.toFixed(2)} m` : "NA"}</strong>
          </div>
          <div className="comparison-card meta">
            <small>Confidence</small>
            <strong>{Number.isFinite(Number(props.confidence)) ? `${Number(props.confidence).toFixed(2)}%` : "NA"}</strong>
          </div>
        </div>
      </div>
      <div className="insight-trend">
        <div className="insight-section-heading" style={{ marginBottom: '8px' }}>
          <small>Groundwater Trend</small>
          <label htmlFor="trend-year-filter" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>Year</span>
            <select id="trend-year-filter" value={safeTrendYear} onChange={(event) => setTrendYear(Number(event.target.value))}>
              {trendYearOptions.map((year) => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </label>
        </div>
        <WaterTrendChart points={trendPoints} predictedValue={predictedDepth} actualLabel="Actual" predictedLabel="Predicted" />
        <p className="insight-muted" style={{ marginTop: '8px' }}>
          Average: {trendAverage !== null ? `${trendAverage.toFixed(2)} m` : "NA"} · Direction: {trendDirection}
        </p>
      </div>
      <div className="insight-trend">
        <div className="insight-section-heading" style={{ marginBottom: '8px' }}>
          <small>Groundwater History</small>
          <label htmlFor="history-year-filter" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>Year</span>
            <select
              id="history-year-filter"
              value={Number.isFinite(Number(groundwaterYear)) ? groundwaterYear : ""}
              onChange={(event) => setGroundwaterYear(Number(event.target.value))}
            >
              {(groundwaterHistory?.available_years?.length ? groundwaterHistory.available_years : trendYearOptions).map((year) => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </label>
        </div>
        {groundwaterHistoryLoading && <p className="insight-muted">Loading groundwater history...</p>}
        {!groundwaterHistoryLoading && (
          <>
            <WaterTrendChart points={groundwaterPoints} predictedValue={groundwaterPredicted} actualLabel="Actual" predictedLabel="Predicted" />
            <div className="insight-comparison-grid" style={{ marginTop: '8px' }}>
              <div className="comparison-card actual">
                <small>Actual Last Month</small>
                <strong>{formatDepth(groundwaterActualLast)}</strong>
              </div>
              <div className="comparison-card predicted">
                <small>Prediction Error</small>
                <strong>{Number.isFinite(groundwaterError) ? `${groundwaterError > 0 ? "+" : ""}${groundwaterError.toFixed(2)} m` : "NA"}</strong>
              </div>
              <div className="comparison-card meta">
                <small>Stations</small>
                <strong>{Number(groundwaterInsights?.obs_station_count ?? props.obs_station_count ?? 0).toFixed(0)}</strong>
              </div>
              <div className="comparison-card meta">
                <small>Trend Slope</small>
                <strong>{Number.isFinite(Number(groundwaterInsights?.trend_slope ?? props.trend_slope)) ? Number(groundwaterInsights?.trend_slope ?? props.trend_slope).toFixed(4) : "NA"}</strong>
              </div>
            </div>
          </>
        )}
        {groundwaterHistoryError && (
          <p className="insight-muted" style={{ marginTop: '8px' }}>{groundwaterHistoryError}</p>
        )}
      </div>
      <div className="insight-recharge">
        <small>Recharge Suggestion</small>
        <p>{rechargeSuggestion}</p>
      </div>
      {aquiferAnalytics && (
        <div className="insight-aquifer">
          <small>Aquifer Analytics</small>
          <div className="insight-metric-grid">
            <div>
              <small>Units Loaded</small>
              <strong>{aquiferAnalytics.totalPolygons}</strong>
            </div>
            <div>
              <small>Total Aquifer Area</small>
              <strong>{aquiferAnalytics.totalAreaKm2.toFixed(2)} kmÂ²</strong>
            </div>
            <div>
              <small>Dominant Aquifer Class</small>
              <strong>{aquiferAnalytics.dominantClass?.name || "NA"}</strong>
            </div>
            <div>
              <small>Selected Village Aquifer</small>
              <strong>{aquiferAnalytics.selectedVillageAquifer?.name || "No overlap"}</strong>
            </div>
          </div>
          {aquiferAnalytics.filteredVillageDominantAquifer && (
            <p className="insight-muted" style={{ marginTop: '8px' }}>
              Active filter dominant aquifer: {aquiferAnalytics.filteredVillageDominantAquifer.name} (
              {aquiferAnalytics.filteredVillageDominantAquifer.villageCount} villages)
            </p>
          )}
        </div>
      )}
      <p className="insight-muted">
        AI Prediction: {aiPredictionEnabled ? "Enabled" : "Disabled"}.
      </p>
    </DraggableInsightsShell>
  );
}

export function DashboardAnalyticsPanel({
  datasetAnalytics,
  selectedFeature,
  onClose
}) {
  const scopeLabel = datasetAnalytics?.scopeLabel || "Dataset overview";
  const lulcBars = datasetAnalytics?.lulcBars || [];
  const lulcDonut = datasetAnalytics?.lulcDonut || [];
  const yearComparison = datasetAnalytics?.yearComparison || [];
  const summaryBars = datasetAnalytics?.summaryBars || [];
  const groundwaterTrend = datasetAnalytics?.groundwaterTrend || null;
  const datasetSummary = datasetAnalytics?.datasetSummary || null;
  const selectedProfile = datasetAnalytics?.selectedProfile || null;
  const selectedRow = datasetAnalytics?.selectedRow || null;
  const loading = Boolean(datasetAnalytics?.loading);
  const error = datasetAnalytics?.error || null;
  const rowCount = Number(datasetAnalytics?.rowCount || 0);
  const loadedCount = Number(datasetAnalytics?.loadedCount || 0);
  const matchedCount = Number(datasetAnalytics?.matchedCount || 0);
  const unmatchedCount = Number(datasetAnalytics?.unmatchedCount || 0);
  const meaningCards = buildMeaningCards(selectedRow);
  const profileFields = buildProfileFields(selectedProfile, selectedRow);
  const [dashboardTrendYear, setDashboardTrendYear] = useState(groundwaterTrend?.defaultYear || null);
  const profileStatus = !selectedProfile
    ? "No selection"
    : (!hasNumericValue(selectedProfile.elevation) || String(selectedProfile.elevation_source || "").toLowerCase().includes("missing_dem"))
      ? "Partial profile"
      : "Complete profile";
  const dashboardTrendYears = groundwaterTrend?.availableYears || [];

  useEffect(() => {
    setDashboardTrendYear(groundwaterTrend?.defaultYear || null);
  }, [groundwaterTrend?.defaultYear, rowCount, selectedRow?.village_id]);

  const safeDashboardTrendYear = dashboardTrendYears.includes(dashboardTrendYear)
    ? dashboardTrendYear
    : groundwaterTrend?.defaultYear || null;
  const dashboardTrendPoints = groundwaterTrend
    ? buildYearlyTrendPoints(
        groundwaterTrend.fullValues || [],
        safeDashboardTrendYear,
        groundwaterTrend.fullLabels || [],
        1998
      )
    : [];

  return (
    <section className="full-dashboard-sheet dashboard-theme-clear" aria-label="Full dashboard analytics">
      <div className="full-dashboard-header">
        <div className="full-dashboard-title">
          <small className="dashboard-kicker">Professional Display Mode</small>
          <h2>Full Dashboard</h2>
          <p>{scopeLabel} | {matchedCount} matched villages | {loadedCount} loaded | {unmatchedCount} unmatched</p>
        </div>
        <button type="button" className="dashboard-close-button" onClick={onClose}>
          Close
        </button>
      </div>

      {loading && <p className="insight-muted">Loading dashboard dataset...</p>}
      {error && <p className="insight-muted">{error}</p>}

      <div className="full-dashboard-summary">
        <div className="summary-tile">
          <small>Rows in Scope</small>
          <strong>{rowCount}</strong>
        </div>
        <div className="summary-tile">
          <small>Matched Villages</small>
          <strong>{matchedCount}</strong>
        </div>
        <div className="summary-tile">
          <small>Loaded Villages</small>
          <strong>{loadedCount}</strong>
        </div>
        <div className="summary-tile">
          <small>Unmatched Villages</small>
          <strong>{unmatchedCount}</strong>
        </div>
        <div className="summary-tile">
          <small>Avg Groundwater</small>
          <strong>{formatNumber(datasetSummary?.gw_level, 2)} m</strong>
        </div>
        <div className="summary-tile">
          <small>Avg Pumping</small>
          <strong>{formatNumber(datasetSummary?.pumping_rate, 2)} hp</strong>
        </div>
        <div className="summary-tile">
          <small>Terrain Gradient</small>
          <strong>{formatNumber(datasetSummary?.terrain_gradient, 2)} m</strong>
        </div>
      </div>

      {selectedProfile && (
        <div className="full-dashboard-profile">
          <div className="profile-summary-banner">
            <div>
              <small>Selected Village</small>
              <strong>{selectedProfile.village_name}</strong>
            </div>
            <span className={`profile-state ${profileStatus === "Complete profile" ? "is-complete" : "is-partial"}`}>
              {profileStatus}
            </span>
          </div>
          {profileFields.map((field) => (
            <div key={field.label} className="profile-field-card">
              <small>{field.label}</small>
              <strong>{field.value}</strong>
              <span>{field.meta}</span>
            </div>
          ))}
          <div className="profile-source-note">
            Source layers: village geometry, piezometer, LULC, aquifer, and soil datasets
          </div>
        </div>
      )}

      {meaningCards.length > 0 && (
        <section className="meaning-panel">
          <div className="insight-section-heading">
            <small>What this means</small>
            <span>Rule-based interpretation</span>
          </div>
          <p className="meaning-disclaimer">
            These notes are generated from the field type and current data quality. If a value is missing or fallback-only, the dashboard hides the confident interpretation.
          </p>
          <div className="meaning-card-grid">
            {meaningCards.map((card) => (
              <article key={card.title} className="meaning-card">
                <strong>{card.title}</strong>
                <span>{card.label}</span>
                <ul>
                  {card.notes.map((note, index) => (
                    <li key={`${card.title}-${index}`}>{note}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>
      )}

      <div className="full-dashboard-grid">
        <ChartCard title="LULC Composition" subtitle="Average share">
          <LulcBarChart data={lulcBars} />
        </ChartCard>
        <ChartCard title="LULC Mix" subtitle="Donut view">
          <DonutChart
            data={lulcDonut}
            centerTitle="LULC"
            centerValue={`${formatNumber(datasetSummary?.count || rowCount, 0)} rows`}
            centerSubtitle="current scope"
          />
        </ChartCard>
        <ChartCard title="2011 vs 2021" subtitle="Grouped bars">
          <ComparisonChart data={yearComparison} />
        </ChartCard>
        <ChartCard title="Groundwater Trend" subtitle="Average monthly depth">
          <div className="insight-section-heading" style={{ marginBottom: '8px' }}>
            <small>Average groundwater across villages</small>
            <label htmlFor="dashboard-trend-year" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>Year</span>
              <select
                id="dashboard-trend-year"
                value={safeDashboardTrendYear || ""}
                onChange={(event) => setDashboardTrendYear(Number(event.target.value))}
              >
                {dashboardTrendYears.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <WaterTrendChart
            points={dashboardTrendPoints}
            predictedValue={groundwaterTrend?.predictedAverage ?? null}
            actualLabel="Actual average"
            predictedLabel="Predicted average"
          />
          <p className="insight-muted" style={{ marginTop: '8px' }}>
            Source: piezometer history from PzWaterLevel_2024.xlsx
          </p>
        </ChartCard>
        <ChartCard title="Hydro Summary" subtitle="Scaled metrics">
          <SummaryBars data={summaryBars} />
        </ChartCard>
      </div>

      {selectedFeature && (
        <p className="insight-muted full-dashboard-note">
          The map selection still drives the selected-village profile while this full dashboard stays wide.
        </p>
      )}
    </section>
  );
}

export function CollapsiblePanel({ title, children, defaultOpen = true }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div style={{ marginBottom: '16px' }}>
      <div className="collapsible-header" onClick={() => setIsOpen(!isOpen)}>
        <h3>{title}</h3>
        <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" style={{ transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
          <path d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      {isOpen && <div style={{ padding: '8px 0' }}>{children}</div>}
    </div>
  );
}

export function ClimateChart({ data }) {
  if (!data || data.length === 0) return <p className="text-muted">No climate data available</p>;
  
  const maxVal = Math.max(...data.map(d => d.value), 1);
  
  return (
    <div className="climate-chart">
      <div className="chart-bars">
        {data.map((d, i) => (
          <div 
            key={i} 
            className="chart-bar" 
            style={{ height: `${(d.value / maxVal) * 100}%` }}
          >
            <div className="bar-tooltip">{d.label}: {d.value}mm</div>
          </div>
        ))}
      </div>
      <div className="chart-labels">
        <span>Jan</span>
        <span>Jun</span>
        <span>Dec</span>
      </div>
    </div>
  );
}

export function VillageDetails({ feature }) {
  const props = feature.properties || {};
  const forecast = props.lstm_forecast || [];
  const advisories = props.advisories || [
    { level: 'Info', text: 'Maintain current extraction levels. Groundwater recharge conditions are optimal.' }
  ];

  return (
    <div className="village-details">
      <h2 style={{ fontSize: '1.2rem', margin: '0 0 4px 0', color: '#fff' }}>
        {props.village_name || "Village Details"}
      </h2>
      <div style={{ color: '#64748b', fontSize: '0.8rem', marginBottom: '12px' }}>
        {props.mandal}, {props.district}
      </div>

      <div className="details-grid">
        <div className="detail-item">
          <label>GEOLOGY</label>
          <span>{props.geology || 'Weathered Granitic Gneiss'}</span>
        </div>
        <div className="detail-item">
          <label>AQUIFER TYPE</label>
          <span>{props.aquifer_type || 'Unconfined / Fractured'}</span>
        </div>
      </div>

      <div className="detail-section">
        <label>RAINFALL TREND (12-MONTH)</label>
        <ClimateChart data={[
          { label: 'Jan', value: 10 }, { label: 'Feb', value: 5 }, { label: 'Mar', value: 15 },
          { label: 'Apr', value: 40 }, { label: 'May', value: 65 }, { label: 'Jun', value: 120 },
          { label: 'Jul', value: 180 }, { label: 'Aug', value: 165 }, { label: 'Sep', value: 140 },
          { label: 'Oct', value: 80 }, { label: 'Nov', value: 30 }, { label: 'Dec', value: 15 }
        ]} />
      </div>

      <div className="detail-section">
        <label>FARMER ADVISORIES</label>
        <div className="advisory-list">
          {advisories.map((a, i) => (
            <div key={i} className={`advisory-item ${a.level.toLowerCase()}`}>
              <div className="advisory-icon">!</div>
              <p>{a.text}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}



