const LULC_SERIES = [
  { key: "water_pct", label: "Water", color: "#38BDF8" },
  { key: "trees_pct", label: "Trees", color: "#22C55E" },
  { key: "flooded_vegetation_pct", label: "Flooded Vegetation", color: "#67E8F9" },
  { key: "crops_pct", label: "Crops", color: "#FACC15" },
  { key: "built_area_pct", label: "Built", color: "#F97316" },
  { key: "bare_ground_pct", label: "Bare", color: "#D1D5DB" },
  { key: "snow_ice_pct", label: "Snow/Ice", color: "#E5E7EB" },
  { key: "clouds_pct", label: "Clouds", color: "#94A3B8" },
  { key: "rangeland_pct", label: "Rangeland", color: "#84CC16" }
];

const YEARLY_SERIES = [
  { key: "water", label: "Water", color: "#38BDF8" },
  { key: "trees", label: "Trees", color: "#22C55E" },
  { key: "flooded_vegetation", label: "Flooded Vegetation", color: "#67E8F9" },
  { key: "crops", label: "Crops", color: "#FACC15" },
  { key: "built", label: "Built", color: "#F97316" },
  { key: "bare", label: "Bare", color: "#D1D5DB" },
  { key: "snow_ice", label: "Snow/Ice", color: "#E5E7EB" },
  { key: "clouds", label: "Clouds", color: "#94A3B8" },
  { key: "rangeland", label: "Rangeland", color: "#84CC16" }
];

const SUMMARY_METRICS = [
  { key: "gw_level", label: "Groundwater", unit: "m" },
  { key: "pumping_rate", label: "Pumping", unit: "hp" },
  { key: "elevation", label: "Elevation", unit: "m" },
  { key: "terrain_gradient", label: "Terrain", unit: "m" },
  { key: "recharge_index", label: "Recharge", unit: "" },
  { key: "extraction_stress", label: "Extraction", unit: "" }
];

function toNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function average(rows, key) {
  const values = rows.map((row) => toNumber(row?.[key], NaN)).filter((value) => Number.isFinite(value));
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + toNumber(row?.[key], 0), 0);
}

function round(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function normalizeSeriesEntry(entry) {
  if (entry === null || entry === undefined || entry === "") return null;
  const numeric = Number(entry);
  return Number.isFinite(numeric) ? numeric : null;
}

function parseSeriesArray(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => normalizeSeriesEntry(entry));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((entry) => normalizeSeriesEntry(entry));
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

function parseNumberArray(value) {
  if (Array.isArray(value)) {
    return value
      .map((entry) => Number(entry))
      .filter((entry) => Number.isFinite(entry));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed
          .map((entry) => Number(entry))
          .filter((entry) => Number.isFinite(entry));
      }
    } catch {
      return [];
    }
  }
  return [];
}

export function getLulcSeries() {
  return LULC_SERIES;
}

export function summarizeRows(rows) {
  const safeRows = Array.isArray(rows) ? rows : [];
  return {
    count: safeRows.length,
    water_pct: round(average(safeRows, "water_pct")),
    trees_pct: round(average(safeRows, "trees_pct")),
    flooded_vegetation_pct: round(average(safeRows, "flooded_vegetation_pct")),
    crops_pct: round(average(safeRows, "crops_pct")),
    built_area_pct: round(average(safeRows, "built_area_pct")),
    bare_ground_pct: round(average(safeRows, "bare_ground_pct")),
    snow_ice_pct: round(average(safeRows, "snow_ice_pct")),
    clouds_pct: round(average(safeRows, "clouds_pct")),
    rangeland_pct: round(average(safeRows, "rangeland_pct")),
    gw_level: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["gw_level"], NaN))) ? average(safeRows, "gw_level") : null, 2),
    pumping_rate: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["pumping_rate"], NaN))) ? average(safeRows, "pumping_rate") : null, 2),
    elevation: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["elevation"], NaN))) ? average(safeRows, "elevation") : null, 2),
    terrain_gradient: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["terrain_gradient"], NaN))) ? average(safeRows, "terrain_gradient") : null, 2),
    recharge_index: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["recharge_index"], NaN))) ? average(safeRows, "recharge_index") : null, 2),
    extraction_stress: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["extraction_stress"], NaN))) ? average(safeRows, "extraction_stress") : null, 2),
    aquifer_storage_factor: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["aquifer_storage_factor"], NaN))) ? average(safeRows, "aquifer_storage_factor") : null, 2),
    built_area_change_pct: round(safeRows.some((row) => Number.isFinite(toNumber(row?.["built_area_change_pct"], NaN))) ? average(safeRows, "built_area_change_pct") : null, 2),
    soil_taxonomy: safeRows.length ? safeRows.find((row) => row?.soil_taxonomy)?.soil_taxonomy || "Unknown" : "Unknown",
    soil_map_unit: safeRows.length ? safeRows.find((row) => row?.soil_map_unit)?.soil_map_unit || "Unknown" : "Unknown",
    aquifer_type: safeRows.length ? safeRows.find((row) => row?.aquifer_type)?.aquifer_type || "Unknown" : "Unknown",
    elevation_source: safeRows.length ? safeRows.find((row) => row?.elevation_source)?.elevation_source || "Unknown" : "Unknown",
    lulc_latest_year: safeRows.length ? safeRows.find((row) => Number.isFinite(Number(row?.lulc_latest_year)))?.lulc_latest_year || null : null,
    village_count: safeRows.length
  };
}

export function buildLulcBars(rows) {
  const safeRows = Array.isArray(rows) ? rows : [];
  return LULC_SERIES.map((item) => ({
    ...item,
    value: round(safeRows.some((row) => Number.isFinite(toNumber(row?.[item.key], NaN))) ? average(safeRows, item.key) : null)
  }));
}

export function buildLulcDonut(rows) {
  const bars = buildLulcBars(rows).filter((entry) => entry.value > 0);
  const top = [...bars].sort((a, b) => b.value - a.value).slice(0, 5);
  const total = bars.reduce((sumValue, entry) => sumValue + entry.value, 0);
  const other = Math.max(0, round(total - top.reduce((sumValue, entry) => sumValue + entry.value, 0)));
  if (other > 0) {
    top.push({ key: "other", label: "Other", color: "#64748B", value: other });
  }
  return top;
}

export function buildYearComparison(rows) {
  const safeRows = Array.isArray(rows) ? rows : [];
  return YEARLY_SERIES.map((item) => {
    const currentKey = `${item.key}_2021_pct`;
    const baselineKey = `${item.key}_2011_pct`;
    const current = round(safeRows.some((row) => Number.isFinite(toNumber(row?.[currentKey], NaN))) ? average(safeRows, currentKey) : null);
    const baseline = round(safeRows.some((row) => Number.isFinite(toNumber(row?.[baselineKey], NaN))) ? average(safeRows, baselineKey) : null);
    return {
      ...item,
      current,
      baseline,
      delta: current === null || baseline === null ? null : round(current - baseline, 2)
    };
  });
}

export function buildSummaryBars(rows) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const metrics = SUMMARY_METRICS.map((item) => {
    const value = round(safeRows.some((row) => Number.isFinite(toNumber(row?.[item.key], NaN))) ? average(safeRows, item.key) : null, item.key === "gw_level" ? 2 : 1);
    return {
      ...item,
      value
    };
  });
  const maxValue = Math.max(...metrics.map((item) => Math.abs(Number(item.value) || 0)), 1);
  return metrics.map((item) => ({
    ...item,
    percent: item.value === null ? 0 : round((Math.abs(item.value) / maxValue) * 100, 1)
  }));
}

export function buildGroundwaterTrend(rows) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const entries = safeRows
    .map((row) => ({
      values: parseSeriesArray(row?.monthly_depths_full ?? row?.monthly_depths),
      labels: parseLabelArray(row?.monthly_depths_full_dates ?? row?.monthly_depths_dates),
      years: parseNumberArray(row?.available_years),
      longTermAvg: Number(row?.long_term_avg),
      trendSlope: Number(row?.trend_slope),
      seasonalVariation: Number(row?.seasonal_variation)
    }))
    .filter((entry) => entry.values.length > 0);

  if (!entries.length) {
    return {
      availableYears: [],
      defaultYear: null,
      fullValues: [],
      fullLabels: [],
      predictedAverage: null,
      actualLastMonth: null
    };
  }

  const maxLength = Math.max(...entries.map((entry) => entry.values.length));
  const fullValues = Array.from({ length: maxLength }, (_, index) => {
    const values = entries
      .map((entry) => Number(entry.values[index]))
      .filter((value) => Number.isFinite(value));
    if (!values.length) return null;
    return round(values.reduce((sum, value) => sum + value, 0) / values.length, 2);
  });

  const fullLabels = entries.find((entry) => entry.labels.length === maxLength)?.labels
    || entries.find((entry) => entry.labels.length)?.labels
    || Array.from({ length: maxLength }, (_, index) => `${index + 1}`);

  const availableYears = Array.from(
    new Set([
      ...entries.flatMap((entry) => entry.years || []),
      ...fullLabels
        .map((label, index) => {
          const match = String(label || "").match(/(20\d{2})/);
          if (match) return Number(match[1]);
          return 1998 + Math.floor(index / 12);
        })
        .filter((year) => Number.isFinite(year))
    ])
  ).sort((a, b) => a - b);

  const actualLastMonth = [...fullValues].reverse().find((value) => Number.isFinite(Number(value))) ?? null;
  const predictedAverage = round(
    safeRows.some((row) => Number.isFinite(toNumber(row?.predicted_groundwater_level, NaN)))
      ? average(safeRows, "predicted_groundwater_level")
      : null,
    2
  );
  const longTermAverage = round(
    safeRows.some((row) => Number.isFinite(toNumber(row?.long_term_avg, NaN)))
      ? average(safeRows, "long_term_avg")
      : null,
    2
  );
  const trendSlope = round(
    safeRows.some((row) => Number.isFinite(toNumber(row?.trend_slope, NaN)))
      ? average(safeRows, "trend_slope")
      : null,
    4
  );
  const seasonalVariation = round(
    safeRows.some((row) => Number.isFinite(toNumber(row?.seasonal_variation, NaN)))
      ? average(safeRows, "seasonal_variation")
      : null,
    2
  );

  return {
    availableYears,
    defaultYear: availableYears[availableYears.length - 1] || null,
    fullValues,
    fullLabels,
    predictedAverage,
    actualLastMonth,
    longTermAverage,
    trendSlope,
    seasonalVariation
  };
}

export function buildVillageHeadline(row) {
  if (!row) return null;
  return {
    village_name: row.village_name || "Selected Village",
    district: row.district || "Unknown",
    mandal: row.mandal || "Unknown",
    soil: row.soil || "Unknown",
    soil_taxonomy: row.soil_taxonomy || "Unknown",
    soil_map_unit: row.soil_map_unit || "Unknown",
    aquifer_type: row.aquifer_type || "Unknown",
    elevation_source: row.elevation_source || "Unknown",
    elevation: round(toNumber(row.elevation, null), 2),
    elevation_min: round(toNumber(row.elevation_min, null), 2),
    elevation_max: round(toNumber(row.elevation_max, null), 2),
    terrain_gradient: round(toNumber(row.terrain_gradient, null), 2),
    aquifer_storage_factor: round(toNumber(row.aquifer_storage_factor, null), 2)
  };
}

export function totalPercentage(rows) {
  return sum(rows, "water_pct") + sum(rows, "trees_pct") + sum(rows, "flooded_vegetation_pct") + sum(rows, "crops_pct") + sum(rows, "built_area_pct") + sum(rows, "bare_ground_pct") + sum(rows, "snow_ice_pct") + sum(rows, "clouds_pct") + sum(rows, "rangeland_pct");
}
