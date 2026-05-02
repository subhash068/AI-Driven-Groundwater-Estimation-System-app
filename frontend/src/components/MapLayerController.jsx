import React from 'react';
import { MAP_MODES } from '../constants/mapModes';

export default function MapLayerController({ mode, setMode }) {
  return (
    <div className="map-layer-controller" style={{ marginBottom: '16px' }}>
      <div className="panel-kicker" style={{ marginBottom: '10px' }}>Map Mode</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {Object.values(MAP_MODES).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            style={{
              padding: '10px 14px',
              borderRadius: '10px',
              border: mode === m ? '1px solid var(--accent)' : '1px solid rgba(255,255,255,0.1)',
              background: mode === m ? 'rgba(0, 229, 255, 0.15)' : 'rgba(255,255,255,0.03)',
              color: mode === m ? 'var(--accent)' : '#94a3b8',
              cursor: 'pointer',
              textAlign: 'left',
              fontWeight: mode === m ? '700' : '500',
              transition: 'all 0.2s ease',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              fontSize: '0.85rem'
            }}
          >
            {m} {m === MAP_MODES.PREDICTION && ' (Default)'}
            {m === MAP_MODES.TREND && ' (Direction)'}
          </button>
        ))}
      </div>
    </div>
  );
}
