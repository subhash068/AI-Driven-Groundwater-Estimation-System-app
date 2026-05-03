const fs = require('fs');
const path = require('path');

const dataDir = path.join(__dirname, '../frontend/public/data');

function checkGeoJson(filename) {
    const p = path.join(dataDir, filename);
    if (!fs.existsSync(p)) return;
    try {
        const data = JSON.parse(fs.readFileSync(p, 'utf8'));
        const features = data.features || [];
        const ids = new Set();
        const names = new Set();
        let duplicatesId = 0;
        let duplicatesName = 0;

        for (const f of features) {
            const props = f.properties || {};
            const id = props.village_id;
            const name = props.village_name || props.Village_Name || props.VILLAGE;
            
            if (id) {
                if (ids.has(id)) duplicatesId++;
                ids.add(id);
            }
            if (name) {
                if (names.has(name)) duplicatesName++;
                names.add(name);
            }
        }
        console.log(`\nFile: ${filename}`);
        console.log(`Total Features: ${features.length}`);
        console.log(`Unique IDs: ${ids.size} (Duplicates: ${duplicatesId})`);
        console.log(`Unique Names: ${names.size} (Duplicates: ${duplicatesName})`);
    } catch(e) {
        console.log(`Error parsing ${filename}: ${e.message}`);
    }
}

function checkJsonList(filename) {
    const p = path.join(dataDir, filename);
    if (!fs.existsSync(p)) return;
    try {
        const data = JSON.parse(fs.readFileSync(p, 'utf8'));
        const list = Array.isArray(data) ? data : (data.features ? data.features : data);
        if (!Array.isArray(list)) {
            console.log(`\nFile: ${filename} - Not a list`);
            return;
        }
        const ids = new Set();
        let duplicatesId = 0;

        for (const row of list) {
            const props = row.properties ? row.properties : row;
            const id = props.village_id;
            if (id) {
                if (ids.has(id)) duplicatesId++;
                ids.add(id);
            }
        }
        console.log(`\nFile: ${filename}`);
        console.log(`Total rows: ${list.length}`);
        console.log(`Unique IDs: ${ids.size} (Duplicates: ${duplicatesId})`);
    } catch(e) {
        console.log(`Error parsing ${filename}: ${e.message}`);
    }
}

['map_data_predictions.geojson', 'map_data_predictions_ntr.geojson', 'village_boundaries.geojson', 'village_boundaries_ntr.geojson', 'villages.geojson'].forEach(checkGeoJson);
['final_dataset.json', 'final_dataset_ntr.json'].forEach(checkJsonList);

