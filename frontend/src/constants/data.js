import pumpingWorkbook from "./pumping_data.json";

export const INDIAN_STATES = [
  "Andhra Pradesh",
  "Arunachal Pradesh",
  "Assam",
  "Bihar",
  "Chhattisgarh",
  "Goa",
  "Gujarat",
  "Haryana",
  "Himachal Pradesh",
  "Jharkhand",
  "Karnataka",
  "Kerala",
  "Madhya Pradesh",
  "Maharashtra",
  "Manipur",
  "Meghalaya",
  "Mizoram",
  "Nagaland",
  "Odisha",
  "Punjab",
  "Rajasthan",
  "Sikkim",
  "Tamil Nadu",
  "Telangana",
  "Tripura",
  "Uttar Pradesh",
  "Uttarakhand",
  "West Bengal",
  "Andaman and Nicobar Islands",
  "Chandigarh",
  "Dadra and Nagar Haveli and Daman and Diu",
  "Delhi",
  "Jammu and Kashmir",
  "Ladakh",
  "Lakshadweep",
  "Puducherry"
];

function normalizeText(value, fallback = "Unknown") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function round(value, digits = 2) {
  return Number(Number(value || 0).toFixed(digits));
}

function buildPumpingSummary(rows) {
  const recordCount = rows.length;
  const avgFunctioningWells = recordCount > 0
    ? round(rows.reduce((sum, row) => sum + toNumber(row.functioning_wells, 0), 0) / recordCount, 2)
    : 0;
  const avgMonsoonDraft = recordCount > 0
    ? round(rows.reduce((sum, row) => sum + toNumber(row.monsoon_draft_ha_m, 0), 0) / recordCount, 3)
    : 0;
  const avgNonMonsoonDraft = recordCount > 0
    ? round(rows.reduce((sum, row) => sum + toNumber(row.non_monsoon_draft_ha_m, 0), 0) / recordCount, 3)
    : 0;

  const mandalTotals = rows.reduce((acc, row) => {
    const mandal = normalizeText(row.mandal);
    if (!mandal) return acc;
    acc[mandal] = (acc[mandal] || 0) + toNumber(row.functioning_wells, 0);
    return acc;
  }, {});

  const topMandals = Object.entries(mandalTotals)
    .map(([mandal, wells]) => ({ mandal, wells: round(wells, 0) }))
    .sort((a, b) => b.wells - a.wells)
    .slice(0, 3);

  const sampleRows = rows.slice(0, 3).map((row) => ({
    district: normalizeText(row.district),
    mandal: normalizeText(row.mandal),
    village: normalizeText(row.village),
    structureType: normalizeText(row.structure_type),
    wells: round(row.functioning_wells, 0),
    monsoonDraftHaM: round(row.monsoon_draft_ha_m, 3),
    nonMonsoonDraftHaM: round(row.non_monsoon_draft_ha_m, 3)
  }));

  return {
    source: pumpingWorkbook?.source || "Pumping Data.xlsx",
    recordCount,
    avgFunctioningWells,
    avgMonsoonDraft,
    avgNonMonsoonDraft,
    topMandals,
    sampleVillages: sampleRows.map((row) => ({
      mandal: row.mandal,
      village: row.village,
      wells: row.wells,
      structureType: row.structureType
    })),
    sampleRows,
    rows
  };
}

export const HYDRO_CLASSES = [
  {
    label: "Monsoon Draft",
    color: "#4c7fd0",
    source: "Pumping Data.xlsx",
    description: "Estimated draft per well during the monsoon season."
  },
  {
    label: "Non-Monsoon Draft",
    color: "#f3d252",
    source: "Pumping Data.xlsx",
    description: "Dry-season pumping pressure for villages and mandals."
  },
  {
    label: "Functioning Wells",
    color: "#86a84d",
    source: "Pumping Data.xlsx",
    description: "Count of active wells contributing to extraction demand."
  },
  {
    label: "Filter Points",
    color: "#a7d5a5",
    source: "PzWaterLevel_2024.xlsx",
    description: "Observation points used to monitor piezometer water levels."
  },
  {
    label: "Principal Aquifer",
    color: "#df3742",
    source: "PzWaterLevel_2024.xlsx",
    description: "Aquifer type associated with each monitoring location."
  },
  {
    label: "Water Level History",
    color: "#f3f0ec",
    source: "PzWaterLevel_2024.xlsx",
    description: "Historical monthly water-level readings across observation stations."
  },
  {
    label: "Total Depth",
    color: "#d3d1cf",
    source: "PzWaterLevel_2024.xlsx",
    description: "Total bore depth in meters for each piezometer record."
  },
  {
    label: "Stratification",
    color: "#efcfaa",
    source: "PzWaterLevel_2024.xlsx",
    description: "Top-to-bottom subsurface layering for aquifer interpretation."
  }
];

export const AQUIFER_COLORS = {
  AL: "#38BDF8",
  BG: "#F59E0B",
  ST: "#EAB308",
  SH: "#8B5CF6",
  LS: "#10B981",
  QZ: "#F97316",
  KH: "#22C55E",
  CK: "#EF4444",
  default: "#67E8F9"
};

const pumpingRows = Array.isArray(pumpingWorkbook?.rows) ? pumpingWorkbook.rows : [];
const pumpingRowsByDistrict = pumpingRows.reduce((acc, row) => {
  const district = normalizeText(row.district, "Unknown");
  if (!acc[district]) {
    acc[district] = [];
  }
  acc[district].push(row);
  return acc;
}, {});

export const DISTRICT_HOVER_DATA = Object.entries(pumpingRowsByDistrict).reduce((acc, [district, rows]) => {
  acc[district] = {
    pumping: buildPumpingSummary(rows),
  };
  return acc;
}, {});

export const INITIAL_VIEW_STATE = {
  longitude: 78.9629,
  latitude: 22.5937,
  zoom: 5
};
