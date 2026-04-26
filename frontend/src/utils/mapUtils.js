import L from "leaflet";

export function normalizeLocationName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\(.*?\)/g, "")
    .replace(/\./g, "")
    .replace(/\s+/g, "")
    .replace(/[^a-z0-9]+/g, "")
    .trim();
}

export function buildLocationKey(district, mandal, villageName = "") {
  return [
    normalizeLocationName(district),
    normalizeLocationName(mandal),
    normalizeLocationName(villageName)
  ].join("|");
}

export function geometryCenter(geometry) {
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

export function healthColor(depth) {
  if (depth >= 30) return [190, 38, 38, 180]; // critical: red
  if (depth >= 20) return [217, 160, 52, 175]; // warning
  return [52, 146, 70, 175]; // safe: green
}

export function advisoryLabel(depth) {
  if (depth >= 30) return "Critical";
  if (depth >= 20) return "Warning";
  return "Safe";
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function pointInRing(point, ring) {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / ((yj - yi) || Number.EPSILON) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInPolygon(point, polygonCoords) {
  if (!Array.isArray(polygonCoords) || !polygonCoords.length) return false;
  const [outerRing, ...holes] = polygonCoords;
  if (!outerRing || !pointInRing(point, outerRing)) return false;
  return !holes.some((hole) => pointInRing(point, hole));
}

export function pointInGeometry(point, geometry) {
  if (!point || !geometry) return false;
  if (geometry.type === "Polygon") {
    return pointInPolygon(point, geometry.coordinates);
  }
  if (geometry.type === "MultiPolygon") {
    return (geometry.coordinates || []).some((polygon) => pointInPolygon(point, polygon));
  }
  return false;
}

function shiftRingFor3D(ring, depthFactor) {
  const lonShift = 0.00005 * depthFactor;
  const latShift = -0.000035 * depthFactor;
  return ring.map(([lon, lat]) => [lon + lonShift, lat + latShift]);
}

export function shiftGeometryFor3D(geometry, depthFactor) {
  if (!geometry) return null;
  if (geometry.type === "Polygon") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((ring) => shiftRingFor3D(ring, depthFactor))
    };
  }
  if (geometry.type === "MultiPolygon") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((poly) =>
        poly.map((ring) => shiftRingFor3D(ring, depthFactor))
      )
    };
  }
  return geometry;
}
