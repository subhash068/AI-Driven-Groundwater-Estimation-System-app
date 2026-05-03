
const fs = require('fs');

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

function geometryCenter(geometry) {
  if (!geometry) return { longitude: 79.74, latitude: 15.91 };
  let coords = [];
  if (geometry.type === "Polygon") {
    coords = geometry.coordinates[0] || [];
  } else if (geometry.type === "MultiPolygon") {
    coords = (geometry.coordinates[0] || [])[0] || [];
  } else if (geometry.type === "Point") {
    const [lon, lat] = geometry.coordinates;
    return { longitude: lon, latitude: lat };
  }
  if (!coords.length) return { longitude: 79.74, latitude: 15.91 };
  const sum = coords.reduce((acc, [lon, lat]) => ({ lon: acc.lon + lon, lat: acc.lat + lat }), {
    lon: 0,
    lat: 0
  });
  return { longitude: sum.lon / coords.length, latitude: sum.lat / coords.length };
}

function getDistance(c1, c2) {
  if (!c1 || !c2) return Infinity;
  const lat1 = c1.latitude || c1[1];
  const lon1 = c1.longitude || c1[0];
  const lat2 = c2.latitude || c2[1];
  const lon2 = c2.longitude || c2[0];
  const dLat = lat2 - lat1;
  const dLon = lon2 - lon1;
  return Math.sqrt(dLat * dLat + dLon * dLon);
}

const candidates = [
  "frontend/public/data/village_boundaries_imputed.geojson",
  "frontend/public/data/village_boundaries_ntr.geojson",
  "frontend/public/data/villages_with_sensors.geojson"
];

const mergedByKey = new Map();

candidates.forEach(p => {
  if (!fs.existsSync(p)) return;
  const data = JSON.parse(fs.readFileSync(p, 'utf8'));
  data.features.forEach((feature, index) => {
    const props = feature.properties || {};
    const lc = Object.fromEntries(Object.entries(props).map(([k, v]) => [String(k).toLowerCase().trim(), v]));
    const rawVillageName = lc.village_name ?? lc.village ?? lc.dvname ?? lc.name;
    const villageId = lc.village_id ?? lc.villageid ?? lc.id ?? index + 1;
    let villageName = String(rawVillageName || "").trim();
    if (!villageName || /^\d+$/.test(villageName)) villageName = `Village ${villageId}`;
    const district = String(lc.district ?? lc.dname ?? "Unknown").trim();
    const mandal = String(lc.mandal ?? lc.mname ?? lc.taluk ?? "Unknown").trim();
    
    const key = buildLocationKey(district, mandal, villageName);
    const isNumericName = /^\d+$/.test(villageName) || villageName.startsWith("Village ");
    
    let existing = mergedByKey.get(key);
    
    if (!existing && isNumericName) {
        const center = geometryCenter(feature.geometry);
        const mandalKey = `${normalizeKeyPart(district)}|${normalizeKeyPart(mandal)}`;
        
        for (const [otherKey, otherFeature] of mergedByKey.entries()) {
           if (otherKey.startsWith(mandalKey)) {
              const otherCenter = geometryCenter(otherFeature.geometry);
              const dist = getDistance(center, otherCenter);
              if (dist < 0.015) {
                existing = otherFeature;
                break;
              }
           }
        }
    }

    if (!existing) {
        mergedByKey.set(key, feature);
    }
  });
});

console.log("Total unique villages after fix:", mergedByKey.size);
