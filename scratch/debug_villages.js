
const fs = require('fs');
const path = require('path');

function normalizeKeyPart(value) {
  let s = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\(v\)$/g, "")
    .replace(/\(m\)$/g, "")
    .replace(/\(ct\)$/g, "")
    .replace(/\(rf\)$/g, "")
    .replace(/\.v$/g, "")
    .replace(/\.m$/g, "")
    .replace(/\./g, "");
    
  return s
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9]+/g, "");
}

function buildLocationKey(district, mandal, villageName = "") {
  return [district, mandal, villageName].map(normalizeKeyPart).join("|");
}

function featureLocationKey(feature) {
  const props = feature?.properties || {};
  return buildLocationKey(props.district, props.mandal, props.village_name);
}

const DISTRICT_VILLAGE_DATASET_CANDIDATES = [
  "frontend/public/data/villages_with_sensors.geojson",
  "frontend/public/data/village_boundaries_imputed.geojson",
  "frontend/public/data/village_boundaries.geojson",
  "frontend/public/data/villages.geojson",
  "frontend/public/data/village_boundaries_ntr.geojson",
  "frontend/public/data/villages_ntr.geojson"
];

const mergedByKey = new Map();
const sourceCounts = {};

DISTRICT_VILLAGE_DATASET_CANDIDATES.forEach(p => {
  if (!fs.existsSync(p)) return;
  const geojson = JSON.parse(fs.readFileSync(p, 'utf8'));
  let fileCount = 0;
  geojson.features.forEach((feature, index) => {
    // Basic normalization as in useVillageData.js
    const p = feature.properties || {};
    const lc = Object.fromEntries(Object.entries(p).map(([k, v]) => [String(k).toLowerCase().trim(), v]));
    const rawVillageName = lc.village_name ?? lc.village ?? lc.dvname ?? lc.name;
    const villageId = lc.village_id ?? lc.villageid ?? lc.id ?? index + 1;
    let villageName = String(rawVillageName || "").trim();
    if (!villageName || /^\d+$/.test(villageName)) villageName = `Village ${villageId}`;
    const district = String(lc.district ?? lc.dname ?? "Unknown").trim();
    const mandal = String(lc.mandal ?? lc.mname ?? lc.taluk ?? "Unknown").trim();
    
    // Inject normalized props as useVillageData does
    const normalizedFeature = {
      ...feature,
      properties: {
        ...p,
        village_id: villageId,
        village_name: villageName,
        district: district,
        mandal: mandal
      }
    };

    const key = featureLocationKey(normalizedFeature);
    if (fileCount < 5) console.log(`  Key: ${key}`);
    if (!mergedByKey.has(key)) {
      mergedByKey.set(key, normalizedFeature);
      fileCount++;
    }
  });
  sourceCounts[p] = fileCount;
  console.log(`${p}: Added ${fileCount} unique villages. Total unique so far: ${mergedByKey.size}`);
});

console.log("\nFinal unique count:", mergedByKey.size);

// Check for duplicates within the final map
const allKeys = Array.from(mergedByKey.keys());
const uniqueKeys = new Set(allKeys);
console.log("Unique keys in map:", uniqueKeys.size);

if (mergedByKey.size === 1822) {
    console.log("\nREPRODUCED! Exactly 1822 villages.");
}
