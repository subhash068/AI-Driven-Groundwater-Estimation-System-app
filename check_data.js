const fs = require('fs');
const path = require('path');

const geojsonPath = path.join(__dirname, 'frontend/public/data/village_boundaries.geojson');
const datasetPath = path.join(__dirname, 'frontend/public/data/final_dataset.json');

const geojson = JSON.parse(fs.readFileSync(geojsonPath, 'utf8'));
const dataset = JSON.parse(fs.readFileSync(datasetPath, 'utf8'));

console.log(`GeoJSON Features: ${geojson.features.length}`);
console.log(`Dataset Rows: ${dataset.length}`);

const geoMap = new Map();
geojson.features.forEach(f => {
  const p = f.properties;
  const id = p.village_id || p.Village_ID || p.ID;
  const name = p.village_name || p.Village_Name || p.NAME || p.VILLAGE;
  geoMap.set(Number(id), { name, mandal: p.mandal || p.Mandal });
});

const dataMap = new Map();
dataset.forEach(r => {
  const id = r.Village_ID || r.village_id;
  const name = r.Village_Name || r.village_name;
  dataMap.set(Number(id), { name, mandal: r.Mandal || r.mandal });
});

console.log("\n--- Checking first 10 IDs ---");
for (let i = 1; i <= 10; i++) {
  const g = geoMap.get(i);
  const d = dataMap.get(i);
  console.log(`ID ${i}:`);
  console.log(`  GeoJSON: ${g ? g.name : 'MISSING'} (${g ? g.mandal : ''})`);
  console.log(`  Dataset: ${d ? d.name : 'MISSING'} (${d ? d.mandal : ''})`);
}

let idMatches = 0;
let nameMatches = 0;

geoMap.forEach((g, id) => {
  const d = dataMap.get(id);
  if (d && d.name.toLowerCase() === g.name.toLowerCase()) {
    idMatches++;
  }
});

const dataNames = new Set(dataset.map(r => (r.Village_Name || r.village_name).toLowerCase()));
geojson.features.forEach(f => {
  const name = (f.properties.village_name || f.properties.Village_Name || f.properties.NAME).toLowerCase();
  if (dataNames.has(name)) {
    nameMatches++;
  }
});

console.log(`\nID + Name matches: ${idMatches}`);
console.log(`Name only matches (regardless of ID): ${nameMatches}`);
