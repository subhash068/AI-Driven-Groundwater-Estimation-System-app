import sys
import os

path = 'frontend/src/components/UI.jsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

start_tag = 'function SmartHydrograph'
end_tag = 'export function VillageDetails'

start_idx = content.find(start_tag)
end_idx = content.find(end_tag)

if start_idx == -1 or end_idx == -1:
    print(f"Error: tags not found. start={start_idx}, end={end_idx}")
    sys.exit(1)

new_block = """function SmartHydrograph({ 
  rainfall = [], 
  recharge = [], 
  actualGW = [], 
  predictedGW = [], 
  dates = []
}) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const [showFullHistory, setShowFullHistory] = useState(false);
  
  const data = useMemo(() => {
    const parse = (val) => {
      if (Array.isArray(val)) return val;
      if (typeof val === 'string') {
        try { return JSON.parse(val); } catch (e) { return []; }
      }
      return [];
    };

    const d_dates = parse(dates);
    const d_rain = parse(rainfall);
    const d_actual = parse(actualGW);
    const d_pred = parse(predictedGW);

    const full = d_dates.map((d, i) => ({
      date: d,
      rainfall: Number(d_rain[i] || 0),
      actual: Number(d_actual[i] || null),
      predicted: Number(d_pred[i] || null),
    })).filter(d => d.date);

    return showFullHistory ? full : full.slice(-13);
  }, [dates, rainfall, actualGW, predictedGW, showFullHistory]);

  if (data.length < 2) return <p className="insight-muted">Insufficient data for hydrograph.</p>;

  const width = 480;
  const height = 300;
  const margin = { top: 50, right: 60, bottom: 60, left: 60 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const maxRain = Math.max(Math.ceil(Math.max(...data.map(d => d.rainfall), 100) / 50) * 50, 100);
  const maxGW = Math.max(Math.ceil(Math.max(...data.map(d => Math.max(d.actual || 0, d.predicted || 0)), 15) / 5) * 5, 15);
  
  const getX = (i) => margin.left + (i / (data.length - 1)) * innerW;
  const getYRain = (v) => margin.top + innerH - (v / maxRain) * innerH; 
  const getYGW = (v) => margin.top + (v / maxGW) * innerH; // 0 at top, increasing downwards

  const getPath = (values, yFunc) => {
    const validPoints = values.map((v, i) => v !== null ? { x: getX(i), y: yFunc(v) } : null).filter(p => p !== null);
    if (validPoints.length < 2) return "";
    
    let d = `M ${validPoints[0].x} ${validPoints[0].y}`;
    for (let i = 0; i < validPoints.length - 1; i++) {
      const p1 = validPoints[i];
      const p2 = validPoints[i + 1];
      const cp1x = p1.x + (p2.x - p1.x) / 3;
      const cp2x = p1.x + (2 * (p2.x - p1.x)) / 3;
      d += ` C ${cp1x} ${p1.y}, ${cp2x} ${p2.y}, ${p2.x} ${p2.y}`;
    }
    return d;
  };

  const actualPath = getPath(data.map(d => d.actual), getYGW);
  const predictedPath = getPath(data.map(d => d.predicted), getYGW);

  return (
    <div className="apwrims-hydrograph" style={{ background: '#ffffff', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)', border: '1px solid #e2e8f0', position: 'relative', color: '#1e293b', marginBottom: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
           <div style={{ width: '32px', height: '32px', background: '#ecfdf5', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
             <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" /><path d="M12 12v9" /><path d="m8 17 4 4 4-4" /></svg>
           </div>
           <div>
             <strong style={{ fontSize: '0.95rem', color: '#0f172a', display: 'block' }}>Hydro-Climatic Profile</strong>
             <small style={{ color: '#64748b', fontSize: '0.7rem' }}>Rainfall vs. Groundwater Depth</small>
           </div>
        </div>
        <button 
          onClick={() => setShowFullHistory(!showFullHistory)}
          style={{ padding: '4px 10px', borderRadius: '6px', border: '1px solid #e2e8f0', background: '#f8fafc', fontSize: '0.7rem', cursor: 'pointer', fontWeight: '600', color: '#475569' }}
        >
          {showFullHistory ? "Last 13 Months" : "View Full History"}
        </button>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}>
        {/* Y-Axis Labels & Grid */}
        {[0, 0.25, 0.5, 0.75, 1].map(p => (
          <g key={p}>
            <line x1={margin.left} y1={margin.top + p * innerH} x2={width - margin.right} y2={margin.top + p * innerH} stroke="#f1f5f9" strokeWidth="1" />
            
            {/* Left Axis (Rainfall) */}
            <text x={margin.left - 12} y={margin.top + (1-p) * innerH} textAnchor="end" fontSize="10" fill="#059669" dominantBaseline="middle" fontWeight="500">
              {Math.round(maxRain * p)}
            </text>
            
            {/* Right Axis (GW Level - Inverted) */}
            <text x={width - margin.right + 12} y={margin.top + p * innerH} textAnchor="start" fontSize="10" fill="#2563eb" dominantBaseline="middle" fontWeight="500">
              {Math.round(maxGW * p)}m
            </text>
          </g>
        ))}

        {/* Axis Titles */}
        <text x={margin.left - 45} y={margin.top + innerH/2} transform={`rotate(-90, ${margin.left - 45}, ${margin.top + innerH/2})`} textAnchor="middle" fontSize="10" fill="#059669" fontWeight="bold">Rainfall (mm)</text>
        <text x={width - margin.right + 45} y={margin.top + innerH/2} transform={`rotate(90, ${width - margin.right + 45}, ${margin.top + innerH/2})`} textAnchor="middle" fontSize="10" fill="#2563eb" fontWeight="bold">Depth (m)</text>

        {/* Rainfall Bars */}
        {data.map((d, i) => (
          <rect
            key={`r-${i}`}
            x={getX(i) - (showFullHistory ? 1 : 6)}
            y={getYRain(d.rainfall)}
            width={showFullHistory ? 2 : 12}
            height={innerH - (getYRain(d.rainfall) - margin.top)}
            fill="#10b981"
            fillOpacity="0.4"
            rx={showFullHistory ? 0 : 2}
          />
        ))}

        {/* Groundwater Paths */}
        {actualPath && <path d={actualPath} fill="none" stroke="#1d4ed8" strokeWidth="2.5" strokeLinecap="round" />}
        {predictedPath && <path d={predictedPath} fill="none" stroke="#60a5fa" strokeWidth="2" strokeDasharray="4,4" opacity="0.6" />}

        {/* Points */}
        {data.map((d, i) => {
          if (showFullHistory && i % (Math.ceil(data.length / 20)) !== 0) return null;
          return (
            <g key={`p-${i}`}>
              {d.actual !== null && (
                <circle cx={getX(i)} cy={getYGW(d.actual)} r={showFullHistory ? 1.5 : 4} fill="#1d4ed8" stroke="#fff" strokeWidth="1" />
              )}
            </g>
          );
        })}

        {/* X-Axis Labels */}
        {data.map((d, i) => {
          const showLabel = showFullHistory ? (i % Math.ceil(data.length / 8) === 0) : true;
          if (!showLabel) return null;
          return (
            <g key={`x-${i}`} transform={`translate(${getX(i)}, ${margin.top + innerH + 15})`}>
              <text textAnchor="middle" fontSize="10" fill="#64748b" fontWeight="500">
                {d.date.split('-')[1]}
              </text>
              <text y="12" textAnchor="middle" fontSize="9" fill="#94a3b8">
                {d.date.split('-')[0]}
              </text>
            </g>
          );
        })}

        {/* Hover Interaction Vertical Line */}
        {hoverIndex !== null && (
          <line x1={getX(hoverIndex)} y1={margin.top} x2={getX(hoverIndex)} y2={margin.top + innerH} stroke="#cbd5e1" strokeDasharray="4,2" />
        )}

        {/* Interaction Area */}
        {data.map((d, i) => (
          <rect
            key={`h-${i}`}
            x={getX(i) - (innerW / (2 * data.length))}
            y={margin.top}
            width={innerW / data.length}
            height={innerH}
            fill="transparent"
            style={{ cursor: 'pointer' }}
            onMouseEnter={() => setHoverIndex(i)}
            onMouseLeave={() => setHoverIndex(null)}
          />
        ))}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: '20px', marginTop: '10px', fontSize: '0.7rem', fontWeight: '500' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '12px', height: '12px', background: '#10b981', opacity: 0.4, borderRadius: '2px' }}></div>
          <span style={{ color: '#059669' }}>Rainfall</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '12px', height: '2px', background: '#1d4ed8' }}></div>
          <span style={{ color: '#1d4ed8' }}>Actual Level</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '12px', height: '2px', background: '#60a5fa', borderStyle: 'dashed', borderTop: '2px dashed #60a5fa' }}></div>
          <span style={{ color: '#60a5fa' }}>AI Predicted</span>
        </div>
      </div>

      {/* Tooltip */}
      {hoverIndex !== null && (
        <div style={{ position: 'absolute', top: '70px', left: getX(hoverIndex) > width/2 ? '20px' : 'auto', right: getX(hoverIndex) <= width/2 ? '20px' : 'auto', background: 'rgba(255, 255, 255, 0.95)', padding: '10px', borderRadius: '8px', border: '1px solid #e2e8f0', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)', fontSize: '0.75rem', zIndex: 20, pointerEvents: 'none' }}>
          <div style={{ fontWeight: '700', marginBottom: '5px', color: '#1e293b', borderBottom: '1px solid #f1f5f9', paddingBottom: '3px' }}>
            {new Date(data[hoverIndex].date).toLocaleString('en-US', { month: 'short', year: 'numeric' })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '15px', marginBottom: '3px' }}>
            <span style={{ color: '#059669' }}>Rainfall:</span>
            <strong style={{ color: '#0f172a' }}>{data[hoverIndex].rainfall.toFixed(1)} mm</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '15px', marginBottom: '3px' }}>
            <span style={{ color: '#1d4ed8' }}>Actual Depth:</span>
            <strong style={{ color: '#0f172a' }}>{data[hoverIndex].actual !== null ? data[hoverIndex].actual.toFixed(2) + ' m' : 'NA'}</strong>
          </div>
          {data[hoverIndex].predicted !== null && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '15px' }}>
              <span style={{ color: '#3b82f6' }}>AI Estimate:</span>
              <strong style={{ color: '#0f172a' }}>{data[hoverIndex].predicted.toFixed(2)} m</strong>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

"""

new_content = content[:start_idx] + new_block + content[end_idx:]
with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Successfully updated SmartHydrograph block.")
