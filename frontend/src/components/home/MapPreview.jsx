import React, { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Tooltip } from "react-leaflet";

const DEFAULT_CENTER = [16.35, 80.85];

function getDepth(feature) {
  const value = Number(feature?.properties?.depth);
  return Number.isFinite(value) ? value : 0;
}

function getWaterColor(feature) {
  const depth = getDepth(feature);
  if (depth >= 30) return "#b91c1c";
  if (depth >= 20) return "#f97316";
  if (depth >= 10) return "#facc15";
  return "#22c55e";
}

function buildAnomalyPoints(features) {
  return features
    .map((feature) => {
      const props = feature?.properties || {};
      const current = Number(props.actual_last_month ?? props.depth ?? NaN);
      const baseline = Number(props.long_term_avg ?? NaN);
      const lat = Number(props.centroid_lat);
      const lon = Number(props.centroid_lon);
      const hasCoords = Number.isFinite(lat) && Number.isFinite(lon);
      if (!hasCoords || !Number.isFinite(current) || !Number.isFinite(baseline)) return null;
      const drop = Number((current - baseline).toFixed(2));
      if (drop < 1.5) return null;
      return {
        id: props.village_id || `${lat}-${lon}`,
        village: props.village_name || "Village",
        drop,
        position: [lat, lon]
      };
    })
    .filter(Boolean)
    .slice(0, 180);
}

function buildPiezometerPoints(features) {
  return features
    .map((feature) => {
      const props = feature?.properties || {};
      const lat = Number(props.centroid_lat);
      const lon = Number(props.centroid_lon);
      // Support multiple possible keys for station count
      const count = Number(props.obs_station_count ?? props.nearby_piezometer_count_10km ?? (props.has_piezometer ? 1 : 0));
      
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || count <= 0) return null;
      return {
        id: props.village_id || `${lat}-${lon}`,
        village: props.village_name || "Village",
        count,
        position: [lat, lon]
      };
    })
    .filter(Boolean)
    .slice(0, 220);
}

export function MapPreview({ villages, stats }) {
  const districtCandidates = useMemo(() => {
    const fromStats = Array.isArray(stats?.district_aggregation?.districts)
      ? stats.district_aggregation.districts
        .map((row) => String(row?.district || "").trim().toUpperCase())
        .filter(Boolean)
      : [];
    const fromVillages = Array.from(new Set(
      (villages?.features || [])
        .map((feature) => String(feature?.properties?.district || "").trim().toUpperCase())
        .filter(Boolean)
    ));
    const combined = Array.from(new Set([...fromStats, ...fromVillages])).sort();
    return combined;
  }, [stats?.district_aggregation?.districts, villages?.features]);
  const firstDistrict = districtCandidates[0] || "";
  const [selectedDistrict, setSelectedDistrict] = useState(firstDistrict);
  const [layers, setLayers] = useState({
    groundwater: true,
    piezometers: true,
    anomalies: true
  });

  useEffect(() => {
    if (!districtCandidates.length) {
      setSelectedDistrict("");
      return;
    }
    if (!districtCandidates.includes(selectedDistrict)) {
      setSelectedDistrict(districtCandidates[0]);
    }
  }, [districtCandidates, selectedDistrict]);

  const previewGeoJson = useMemo(() => {
    const sourceFeatures = villages?.features || [];
    const filtered = sourceFeatures
      .filter((feature) => String(feature?.properties?.district || "").toUpperCase() === String(selectedDistrict).toUpperCase())
      .slice(0, 320);
    return { type: "FeatureCollection", features: filtered };
  }, [villages, selectedDistrict]);

  const activeDistrictRow = useMemo(() => {
    const rows = Array.isArray(stats?.district_aggregation?.districts)
      ? stats.district_aggregation.districts
      : [];
    return rows.find((row) => String(row?.district || "").toUpperCase() === String(selectedDistrict).toUpperCase()) || null;
  }, [selectedDistrict, stats?.district_aggregation?.districts]);

  const piezometers = useMemo(
    () => buildPiezometerPoints(previewGeoJson.features || []),
    [previewGeoJson]
  );
  const anomalies = useMemo(
    () => buildAnomalyPoints(previewGeoJson.features || []),
    [previewGeoJson]
  );

  const onToggle = (key) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <section id="map-preview" className="home-section reveal-up">
      <div className="section-head">
        <p className="section-chip">Interactive Preview</p>
        <h2>Working Groundwater Map</h2>
        <p>This is not theory. Layered village intelligence is live and explorable.</p>
      </div>

      <div className="map-preview-shell">
        <div className="map-toggle-panel">
          <h3>Layers</h3>
          <label>
            District
            <select value={selectedDistrict} onChange={(e) => setSelectedDistrict(e.target.value)}>
              {districtCandidates.map((district) => (
                <option key={district} value={district}>{district}</option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={layers.groundwater}
              onChange={() => onToggle("groundwater")}
            />
            Groundwater
          </label>
          <label>
            <input
              type="checkbox"
              checked={layers.piezometers}
              onChange={() => onToggle("piezometers")}
            />
            Piezometers
          </label>
          <label>
            <input
              type="checkbox"
              checked={layers.anomalies}
              onChange={() => onToggle("anomalies")}
            />
            Anomalies
          </label>
        </div>

        <div className="map-canvas">
          <div className="map-insight-badge" aria-live="polite">
            <p>
              <strong>High-risk villages:</strong>{" "}
              {Number.isFinite(Number(activeDistrictRow?.high_risk_count))
                ? Number(activeDistrictRow.high_risk_count).toLocaleString()
                : "N/A"}
            </p>
            <p>
              <strong>Avg trend:</strong>{" "}
              {Number.isFinite(Number(activeDistrictRow?.avg_trend_slope))
                ? `${Number(activeDistrictRow.avg_trend_slope).toFixed(2)} m/year`
                : "N/A"}
            </p>
            <p>
              <strong>District:</strong> {selectedDistrict}
            </p>
          </div>
          <MapContainer center={DEFAULT_CENTER} zoom={8} zoomControl style={{ height: "100%", width: "100%" }}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" />

            {layers.groundwater && (
              <GeoJSON
                data={previewGeoJson}
                style={(feature) => ({
                  color: "#155e75",
                  weight: 0.4,
                  fillColor: getWaterColor(feature),
                  fillOpacity: 0.5
                })}
              />
            )}

            {layers.piezometers &&
              piezometers.map((point) => (
                <CircleMarker
                  key={`pz-${point.id}`}
                  center={point.position}
                  radius={3.5}
                  pathOptions={{ color: "#0369a1", fillColor: "#38bdf8", fillOpacity: 0.95, weight: 0.9 }}
                >
                  <Tooltip direction="top" offset={[0, -6]} opacity={0.95}>
                    {point.village}: {point.count} station{point.count > 1 ? "s" : ""}
                  </Tooltip>
                </CircleMarker>
              ))}

            {layers.anomalies &&
              anomalies.map((point) => (
                <CircleMarker
                  key={`an-${point.id}`}
                  center={point.position}
                  radius={5}
                  pathOptions={{ color: "#7f1d1d", fillColor: "#ef4444", fillOpacity: 0.9, weight: 1.1 }}
                >
                  <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                    {point.village}: +{point.drop} m deviation
                  </Tooltip>
                </CircleMarker>
              ))}
          </MapContainer>
        </div>
      </div>
    </section>
  );
}
