const fs = require('fs');
const path = require('path');

const dataDir = path.join(__dirname, '../frontend/public/data');
const files = fs.readdirSync(dataDir).filter(f => f.endsWith('.json') || f.endsWith('.geojson'));

function getVillageId(props) {
    return props.village_id || props.Village_ID || props.VillageID || props.VILLAGE_ID || props.v_id;
}

files.forEach(filename => {
    const p = path.join(dataDir, filename);
    try {
        const content = fs.readFileSync(p, 'utf8');
        if (!content.trim()) return;
        const data = JSON.parse(content);
        
        let items = [];
        if (data.type === 'FeatureCollection') {
            items = data.features;
        } else if (Array.isArray(data)) {
            items = data;
        } else if (typeof data === 'object') {
            // Check if it's a list under some key
            const listKey = Object.keys(data).find(k => Array.isArray(data[k]));
            if (listKey) items = data[listKey];
        }

        const ids = new Map();
        let dups = 0;
        let count = 0;

        items.forEach((item, idx) => {
            const props = item.properties || item;
            const id = getVillageId(props);
            if (id !== undefined && id !== null) {
                count++;
                if (ids.has(id)) {
                    dups++;
                } else {
                    ids.set(id, true);
                }
            }
        });

        if (count > 0) {
            console.log(`[${dups === 0 ? 'PASS' : 'FAIL'}] ${filename}: Checked ${count} IDs, Found ${dups} duplicates.`);
        }
    } catch (e) {
        // console.log(`Skipping ${filename}: Not a village-ID list or parse error.`);
    }
});
