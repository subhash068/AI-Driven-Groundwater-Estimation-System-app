
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
  "frontend/public/data/village_boundaries_ntr.geojson"
];

const mergedByKey = new Map();

DISTRICT_VILLAGE_DATASET_CANDIDATES.forEach(p => {
  if (!fs.existsSync(p)) return;
  const geojson = JSON.parse(fs.readFileSync(p, 'utf8'));
  console.log(`\nFile: ${p}`);
  geojson.features.forEach((feature, index) => {
    const props = feature.properties || {};
    const lc = Object.fromEntries(Object.entries(props).map(([k, v]) => [String(k).toLowerCase().trim(), v]));
    const rawVillageName = lc.village_name ?? lc.village ?? lc.dvname ?? lc.name;
    const villageId = lc.village_id ?? lc.villageid ?? lc.id ?? index + 1;
    let villageName = String(rawVillageName || "").trim();
    if (!villageName || /^\d+$/.test(villageName)) villageName = `Village ${villageId}`;
    const district = String(lc.district ?? lc.dname ?? "Unknown").trim();
    const mandal = String(lc.mandal ?? lc.mname ?? lc.taluk ?? "Unknown").trim();
    
    const key = buildLocationKey(district, mandal, villageName);
    if (index < 5) {
        console.log(`  Original name: "${rawVillageName}", District: "${district}", Mandal: "${mandal}"`);
        console.log(`  Generated key: ${key}`);
    }

    if (!mergedByKey.has(key)) {
      mergedByKey.set(key, feature);
    }
  });
});

console.log("\nFinal unique count:", mergedByKey.size);
