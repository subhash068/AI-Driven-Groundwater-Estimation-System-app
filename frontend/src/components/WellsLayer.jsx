import React, { useEffect, useState, useMemo } from 'react';
import { useMap, CircleMarker, Tooltip } from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import 'react-leaflet-cluster/dist/assets/MarkerCluster.css';
import 'react-leaflet-cluster/dist/assets/MarkerCluster.Default.css';
import { Marker } from 'react-leaflet';
import L from 'leaflet';

function getRadius(value) {
  return Math.max(3.5, Math.sqrt(value) * 1.2);
}

function getColor(value) {
  if (value > 150) return "#1e3a8a"; // very high
  if (value > 80) return "#2563eb";  // high
  if (value > 30) return "#3b82f6";  // moderate
  return "#60a5fa";                  // low
}

const createClusterIcon = (cluster) => {
  const markers = cluster.getAllChildMarkers();
  const totalWells = markers.reduce((sum, marker) => {
    return sum + (marker.options.wellCount || 0);
  }, 0);

  const formatCount = (num) => {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
    return num;
  };

  return L.divIcon({
    html: `<div class="cluster-bubble">${formatCount(totalWells)}</div>`,
    className: "cluster-icon",
    iconSize: [38, 38],
  });
};

function WellClusterLayer({ data }) {
  return (
    <MarkerClusterGroup 
      iconCreateFunction={createClusterIcon}
      showCoverageOnHover={false}
      chunkedLoading
    >
      {data.map((v, i) => (
        <Marker key={i} position={[v.lat, v.lng]} wellCount={v.well_count} />
      ))}
    </MarkerClusterGroup>
  );
}

function WellCircleLayer({ data }) {
  return (
    <>
      {data.map((v, i) => (
        <CircleMarker
          key={i}
          center={[v.lat, v.lng]}
          radius={getRadius(v.well_count)}
          pathOptions={{
            fillColor: getColor(v.well_count),
            fillOpacity: 0.7,
            color: "#0f172a", // slight border for definition
            weight: 1
          }}
        >
          <Tooltip sticky direction="top" className="wells-tooltip">
            <div style={{ minWidth: "180px", fontFamily: "sans-serif" }}>
              <strong>Village:</strong> {v.village}<br/>
              <strong>District:</strong> {v.district}<br/>
              <strong>Estimated Wells:</strong> {v.well_count}<br/>
              <br/>
              <span style={{ fontSize: "0.85em", opacity: 0.85, display: "block", borderTop: "1px solid rgba(255,255,255,0.2)", paddingTop: "6px", marginTop: "6px" }}>
                <em>Village-level estimate only.</em>
              </span>
            </div>
          </Tooltip>
        </CircleMarker>
      ))}
    </>
  );
}

export default function WellsLayerController({ data }) {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  const memoData = useMemo(() => data || [], [data]);

  useEffect(() => {
    const handleZoom = () => setZoom(map.getZoom());
    map.on("zoomend", handleZoom);
    return () => map.off("zoomend", handleZoom);
  }, [map]);

  if (!memoData || memoData.length === 0) return null;

  if (zoom < 10) {
    return <WellClusterLayer data={memoData} />;
  }
  return <WellCircleLayer data={memoData} />;
}
