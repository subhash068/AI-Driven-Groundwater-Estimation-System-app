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

function WellClusterLayer({ data, onVillageClick }) {
  return (
    <MarkerClusterGroup 
      iconCreateFunction={createClusterIcon}
      showCoverageOnHover={false}
      chunkedLoading
    >
      {data.map((v, i) => {
        const vid = v.feature?.properties?.village_id || v.id || i;
        return (
          <Marker 
            key={`cluster-marker-${vid}`} 
            position={[v.lat, v.lng]} 
            wellCount={v.well_count}
            eventHandlers={{
              click: (e) => {
                if (e.originalEvent) {
                  e.originalEvent.stopPropagation();
                  if (e.originalEvent.stopImmediatePropagation) {
                    e.originalEvent.stopImmediatePropagation();
                  }
                }
                if (onVillageClick && v.feature) {
                  onVillageClick(v.feature);
                }
              }
            }}
          />
        );
      })}
    </MarkerClusterGroup>
  );
}

function WellCircleLayer({ data, onVillageClick }) {
  return (
    <>
      {data.map((v, i) => {
        const vid = v.feature?.properties?.village_id || v.id || i;
        return (
          <CircleMarker
            key={`circle-marker-${vid}`}
            center={[v.lat, v.lng]}
            radius={getRadius(v.well_count)}
            eventHandlers={{
              click: (e) => {
                if (e.originalEvent) {
                  e.originalEvent.stopPropagation();
                  if (e.originalEvent.stopImmediatePropagation) {
                    e.originalEvent.stopImmediatePropagation();
                  }
                }
                if (onVillageClick && v.feature) {
                  onVillageClick(v.feature);
                }
              }
            }}
            pathOptions={{
              fillColor: getColor(v.well_count),
              fillOpacity: 0.85, // slightly more opaque for visibility
              color: "#ffffff",   // white border to stand out against polygon
              weight: 1.5,
              pane: 'markerPane'  // try to force it to a higher pane
            }}
          >
            <Tooltip sticky direction="top" className="wells-tooltip">
              <div style={{ minWidth: "190px", fontFamily: "'Inter', sans-serif", color: "#e2e8f0", lineHeight: 1.5 }}>
                <strong style={{ color: "#fff", fontSize: "0.95rem", display: "block", marginBottom: "6px", borderBottom: "1px solid rgba(255,255,255,0.15)", paddingBottom: "4px" }}>Agricultural Infrastructure</strong>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div><span style={{ color: "#94a3b8", fontWeight: 600 }}>Village:</span> <span style={{ color: "#fff" }}>{v.village}</span></div>
                  <div><span style={{ color: "#94a3b8", fontWeight: 600 }}>District:</span> <span style={{ color: "#fff" }}>{v.district}</span></div>
                  <div><span style={{ color: "#94a3b8", fontWeight: 600 }}>Total Wells:</span> <span style={{ color: "#00e5ff", fontWeight: 800 }}>{v.well_count}</span></div>
                </div>
                <div style={{ fontSize: "0.65rem", color: "#64748b", fontStyle: "italic", marginTop: "8px", borderTop: "1px solid rgba(255,255,255,0.05)", paddingTop: "6px" }}>
                  Village-level groundwater extraction infrastructure estimate.
                </div>
              </div>
            </Tooltip>
          </CircleMarker>
        );
      })}
    </>
  );
}

export default function WellsLayerController({ data, onVillageClick }) {
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
    return <WellClusterLayer data={memoData} onVillageClick={onVillageClick} />;
  }
  return <WellCircleLayer data={memoData} onVillageClick={onVillageClick} />;
}
