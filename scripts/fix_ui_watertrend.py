import sys
import os

path = 'frontend/src/components/UI.jsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

start_tag = 'function WaterTrendChart'
end_tag = 'function DraggableInsightsShellLegacy'

start_idx = content.find(start_tag)
end_idx = content.find(end_tag)

if start_idx == -1 or end_idx == -1:
    print(f"Error: tags not found. start={start_idx}, end={end_idx}")
    sys.exit(1)

new_block = """function WaterTrendChart({
  points,
  forecastPoints = [],
  predictedValue = null,
  actualLabel = "Actual average",
  predictedLabel = "AI yearly forecast",
  yAxisLabel = "Depth (m below ground)"
}) {
  const [hoverPoint, setHoverPoint] = useState(null);
  
  const observedSeries = useMemo(() => {
    if (!Array.isArray(points)) return [];
    return points
      .map((p, i) => ({
        label: String(p?.label || 1998 + i),
        value: Number(p?.value),
        kind: "observed"
      }))
      .filter(p => Number.isFinite(p.value));
  }, [points]);

  const forecastSeries = useMemo(() => {
    if (!Array.isArray(forecastPoints)) return [];
    return forecastPoints
      .map((p, i) => ({
        label: String(p?.label || "Forecast"),
        value: Number(p?.value ?? p?.predicted_groundwater_depth),
        kind: "forecast"
      }))
      .filter(p => Number.isFinite(p.value));
  }, [forecastPoints]);

  const series = [...observedSeries, ...forecastSeries];
  if (series.length === 0) return <p className="insight-muted">No yearly series available.</p>;

  const width = 480;
  const height = 300;
  const margin = { top: 50, right: 60, bottom: 60, left: 60 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const warningThreshold = 20;
  const criticalThreshold = 30;
  
  const maxVal = Math.max(
    ...series.map(s => s.value),
    criticalThreshold,
    10
  );
  const roundedMax = Math.ceil(maxVal / 10) * 10;

  const getX = (i) => margin.left + (i / (series.length - 1)) * innerW;
  const getY = (v) => margin.top + (v / roundedMax) * innerH; // 0 at top

  const getStatus = (v) => {
    if (v >= criticalThreshold) return { label: "Critical", color: "#ef4444" };
    if (v >= warningThreshold) return { label: "Warning", color: "#f59e0b" };
    return { label: "Safe", color: "#22c55e" };
  };

  const getPath = (pts) => {
    if (pts.length < 2) return "";
    let d = `M ${getX(0)} ${getY(pts[0].value)}`;
    for (let i = 1; i < pts.length; i++) {
      d += ` L ${getX(i)} ${getY(pts[i].value)}`;
    }
    return d;
  };

  const trendDirection = buildWaterTrendDirection(observedSeries.map(s => s.value));

  return (
    <div className="apwrims-hydrograph" style={{ background: '#ffffff', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)', border: '1px solid #e2e8f0', position: 'relative', color: '#1e293b', marginBottom: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
           <div style={{ width: '32px', height: '32px', background: '#f0f9ff', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
             <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0369a1" strokeWidth="2"><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" /></svg>
           </div>
           <div>
             <strong style={{ fontSize: '0.95rem', color: '#0f172a', display: 'block' }}>Groundwater Trend</strong>
             <small style={{ color: '#64748b', fontSize: '0.7rem' }}>Yearly averages & AI forecast</small>
           </div>
        </div>
        <div style={{ textAlign: 'right' }}>
           <div style={{ fontSize: '0.85rem', fontWeight: '700', color: trendDirection.label.includes('Declin') ? '#ef4444' : '#059669' }}>
             {trendDirection.arrow} {trendDirection.label}
           </div>
           <small style={{ color: '#94a3b8', fontSize: '0.65rem' }}>Long-term trajectory</small>
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}>
        {/* Background Grid & Thresholds */}
        {[0, 0.25, 0.5, 0.75, 1].map(p => (
          <g key={p}>
            <line x1={margin.left} y1={margin.top + p * innerH} x2={width - margin.right} y2={margin.top + p * innerH} stroke="#f1f5f9" strokeWidth="1" />
            <text x={margin.left - 10} y={margin.top + p * innerH} textAnchor="end" fontSize="10" fill="#94a3b8" dominantBaseline="middle">
              {Math.round(roundedMax * p)}m
            </text>
          </g>
        ))}

        {/* Warning & Critical Zones */}
        <line x1={margin.left} y1={getY(warningThreshold)} x2={width - margin.right} y2={getY(warningThreshold)} stroke="#f59e0b" strokeWidth="1" strokeDasharray="4,4" opacity="0.4" />
        <text x={width - margin.right + 5} y={getY(warningThreshold)} fontSize="9" fill="#f59e0b" dominantBaseline="middle" opacity="0.6">Warning</text>

        <line x1={margin.left} y1={getY(criticalThreshold)} x2={width - margin.right} y2={getY(criticalThreshold)} stroke="#ef4444" strokeWidth="1" strokeDasharray="4,4" opacity="0.4" />
        <text x={width - margin.right + 5} y={getY(criticalThreshold)} fontSize="9" fill="#ef4444" dominantBaseline="middle" opacity="0.6">Critical</text>

        {/* Lines */}
        {observedSeries.length > 1 && (
          <path d={getPath(observedSeries)} fill="none" stroke="#0ea5e9" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        )}
        {forecastSeries.length > 0 && (
          <path 
            d={`M ${getX(observedSeries.length - 1)} ${getY(observedSeries[observedSeries.length - 1]?.value)} L ${forecastSeries.map((p, i) => `${getX(observedSeries.length + i)},${getY(p.value)}`).join(" ")}`} 
            fill="none" stroke="#6366f1" strokeWidth="2" strokeDasharray="6,4" strokeLinecap="round" strokeLinejoin="round"
          />
        )}

        {/* Points */}
        {series.map((p, i) => (
          <g key={`p-${i}`} onMouseEnter={() => setHoverPoint(p)} onMouseLeave={() => setHoverPoint(null)} style={{ cursor: 'pointer' }}>
            <circle 
              cx={getX(i)} 
              cy={getY(p.value)} 
              r={hoverPoint === p ? 6 : 4} 
              fill={getStatus(p.value).color} 
              stroke="#fff" 
              strokeWidth="1.5" 
            />
          </g>
        ))}

        {/* X-Axis */}
        {series.map((p, i) => {
          const skip = series.length > 12 ? (i % Math.ceil(series.length / 6) !== 0) : false;
          if (skip) return null;
          return (
            <text key={`x-${i}`} x={getX(i)} y={margin.top + innerH + 20} textAnchor="middle" fontSize="10" fill="#94a3b8" fontWeight="500">
              {p.label}
            </text>
          );
        })}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '15px', marginTop: '15px', fontSize: '0.7rem', fontWeight: '600' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '8px', height: '8px', background: '#22c55e', borderRadius: '50%' }}></div>
          <span style={{ color: '#64748b' }}>Safe</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '8px', height: '8px', background: '#f59e0b', borderRadius: '50%' }}></div>
          <span style={{ color: '#64748b' }}>Warning</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '8px', height: '8px', background: '#ef4444', borderRadius: '50%' }}></div>
          <span style={{ color: '#64748b' }}>Critical</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginLeft: '10px' }}>
          <div style={{ width: '12px', height: '2px', background: '#0ea5e9' }}></div>
          <span style={{ color: '#64748b' }}>Observed</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '12px', height: '2px', background: '#6366f1', borderTop: '2px dashed #6366f1' }}></div>
          <span style={{ color: '#64748b' }}>AI Forecast</span>
        </div>
      </div>

      {/* Tooltip */}
      {hoverPoint && (
        <div style={{ position: 'absolute', top: margin.top, left: '50%', transform: 'translateX(-50%)', background: 'rgba(15, 23, 42, 0.9)', color: '#fff', padding: '8px 12px', borderRadius: '6px', fontSize: '0.75rem', zIndex: 10, pointerEvents: 'none', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)' }}>
          <div style={{ fontWeight: 'bold', marginBottom: '2px' }}>{hoverPoint.kind === 'forecast' ? 'AI Forecast' : 'Observed'} - {hoverPoint.label}</div>
          <div>Depth: <strong>{hoverPoint.value.toFixed(2)} m</strong></div>
          <div style={{ color: getStatus(hoverPoint.value).color, marginTop: '2px', fontWeight: '600' }}>Status: {getStatus(hoverPoint.value).label}</div>
        </div>
      )}
    </div>
  );
}\n\n"""

new_content = content[:start_idx] + new_block + content[end_idx:]
with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Successfully updated WaterTrendChart block.")
