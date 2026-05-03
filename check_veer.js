const fs = require('fs');
const path = require('path');

const geojsonPath = path.join(__dirname, 'frontend/public/data/village_boundaries.geojson');
const datasetPath = path.join(__dirname, 'frontend/public/data/final_dataset.json');

const geojson = JSON.parse(fs.readFileSync(geojsonPath, 'utf8'));
const dataset = JSON.parse(fs.readFileSync(datasetPath, 'utf8'));

const v_geo = geojson.features.find(f => (f.properties.village_name || f.properties.Village_Name || f.properties.NAME || '').toUpperCase().includes('VEERULLAPADU'));
const v_data = dataset.find(r => (r.Village_Name || r.village_name || '').toUpperCase().includes('VEERULLAPADU'));

console.log("GeoJSON Veerullapadu:");
console.log(JSON.stringify(v_geo ? v_geo.properties : 'NOT FOUND', null, 2));

console.log("\nDataset Veerullapadu:");
console.log(JSON.stringify(v_data ? { 
    Village_ID: v_data.Village_ID, 
    Village_Name: v_data.Village_Name, 
    Mandal: v_data.Mandal, 
    District: v_data.District 
} : 'NOT FOUND', null, 2));
