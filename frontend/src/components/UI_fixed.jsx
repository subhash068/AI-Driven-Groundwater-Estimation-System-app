import React, { useEffect, useMemo, useRef, useState } from 'react';
import { advisoryLabel } from '../utils/mapUtils';

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

function normalizeRiskLabel(value, fallbackDepth = null) {
  const text = String(value || "").trim().toLowerCase();
  if (["critical", "severe", "high"].includes(text)) return "Critical";
  if (["warning", "medium", "moderate"].includes(text)) return "Warning";
  if (["safe", "low", "good"].includes(text)) return "Safe";
  if (Number.isFinite(Number(fallbackDepth))) {
    return advisoryLabel(Number(fallbackDepth));
  }
  return "NA";
}

function riskClassName(risk) {
  const normalized = normalizeRiskLabel(risk);
  if (normalized === "Critical") return "is-critical";
  if (normalized === "Warning") return "is-medium";
  if (normalized === "Safe") return "is-safe";
  return "";
}

function formatConfidencePercent(value, digits = 2) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "NA";
  const scaled = numeric <= 1 ? numeric * 100 : numeric;
  const bounded = Math.max(0, Math.min(100, scaled));
  return `${bounded.toFixed(digits)}%`;
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

function getTrendClassification(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return { label: "N/A", tone: "neutral", icon: "⚪" };
  if (num < -0.02) return { label: "Improving", tone: "recharge", icon: "🔵" };
  if (num >= -0.02 && num <= 0.02) return { label: "Stable", tone: "stable", icon: "🟢" };
  if (num > 0.02 && num <= 0.05) return { label: "Moderate Depletion", tone: "warn", icon: "🟡" };
  if (num > 0.05) return { label: "Severe Depletion", tone: "critical", icon: "🔴" };
  return { label: "Stable", tone: "stable", icon: "🟢" };
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
