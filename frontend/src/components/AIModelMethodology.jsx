import React from 'react';
import './AIModelMethodology.css';

export function AIModelMethodology({ isPage = false, onClose }) {
  const content = (
    <div className={`methodology-container ${isPage ? 'is-page' : 'is-modal'}`}>
      <div className="methodology-header">
        <div className="methodology-title-group">
          <div className="methodology-badge">TECHNICAL METHODOLOGY</div>
          <h1>Hybrid Spatio-Temporal AI Model</h1>
        </div>
        {!isPage && <button className="methodology-close" onClick={onClose}>✕</button>}
      </div>

      <div className="methodology-content">
          <section className="methodology-section">
            <div className="section-number">01</div>
            <div className="section-body">
              <h2>Data Ingestion: Multi-Dimensional Input Features</h2>
              <p>The system estimates groundwater levels by analyzing a complex dataset for each village, integrating physical geography with human activity.</p>
              
              <div className="feature-grid">
                <div className="feature-card">
                  <h3>Hydrogeological Data</h3>
                  <p>Analyzes <strong>soil taxonomy</strong> and <strong>aquifer types</strong> (alluvial, basalt, etc.) to determine water infiltration rates and storage capacity.</p>
                </div>
                <div className="feature-card">
                  <h3>Spatial Geography</h3>
                  <p>Incorporates <strong>Elevation (DEM)</strong>, terrain gradient, and proximity to water bodies like <strong>Tanks, Canals, and Streams</strong>.</p>
                </div>
                <div className="feature-card">
                  <h3>Land Use (LULC)</h3>
                  <p>Weights <strong>built-up area</strong> (blocking recharge) against <strong>crop area</strong> (increasing pumping demand) using high-resolution satellite data.</p>
                </div>
                <div className="feature-card">
                  <h3>Climate Data</h3>
                  <p>Integrates <strong>historical rainfall patterns</strong> and seasonal monsoon behavior to model the system's recharge response.</p>
                </div>
              </div>
            </div>
          </section>

          <section className="methodology-section">
            <div className="section-number">02</div>
            <div className="section-body">
              <h2>Model Architecture: ST-GNN + LSTM</h2>
              <p>The core engine combines spatial intelligence with temporal memory to create a robust estimation framework.</p>
              
              <div className="architecture-grid">
                <div className="arch-item">
                  <div className="arch-icon spatial">S</div>
                  <div>
                    <h3>Spatial Component (Graph Neural Network)</h3>
                    <p>Villages are treated as <strong>nodes in a graph</strong>. The model learns spatial dependencies, such as how a village near a tank recharges downstream neighbors.</p>
                  </div>
                </div>
                <div className="arch-item">
                  <div className="arch-icon temporal">T</div>
                  <div>
                    <h3>Temporal Component (LSTM)</h3>
                    <p>Uses <strong>Long Short-Term Memory</strong> networks to learn the "memory" of the water table, understanding how it responds over time to monsoon cycles.</p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="methodology-section">
            <div className="section-number">03</div>
            <div className="section-body">
              <h2>Feature Engineering & Normalization</h2>
              <p>Raw data is transformed into actionable metrics to ensure model consistency across diverse geographic regions.</p>
              
              <ul className="logic-list">
                <li>
                  <strong>Recharge Score:</strong> Computed potential for water to enter the ground based on soil, slope, and surface water proximity.
                </li>
                <li>
                  <strong>Monsoon Draft:</strong> Estimated volume of water extracted for irrigation based on crop intensity and functioning wells.
                </li>
                <li>
                  <strong>Sensor Weighting:</strong> Distance to the nearest physical Piezometer is used to weight the reliability and confidence of the AI estimate.
                </li>
              </ul>
            </div>
          </section>

          <section className="methodology-section">
            <div className="section-number">04</div>
            <div className="section-body">
              <h2>Output & Risk Mapping</h2>
              <p>The model outputs a predicted <strong>Depth Below Ground Level (BGL)</strong> in meters, which is then mapped to actionable risk tiers.</p>
              
              <div className="risk-legend">
                <div className="risk-tier tier-safe">
                  <div className="tier-dot"></div>
                  <div className="tier-info">
                    <strong>Safe</strong>
                    <span>&lt; 20m depth</span>
                  </div>
                </div>
                <div className="risk-tier tier-warning">
                  <div className="tier-dot"></div>
                  <div className="tier-info">
                    <strong>Warning</strong>
                    <span>20m - 30m depth</span>
                  </div>
                </div>
                <div className="risk-tier tier-critical">
                  <div className="tier-dot"></div>
                  <div className="tier-info">
                    <strong>Critical</strong>
                    <span>&gt; 30m depth</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <div className="methodology-footer">
            <p>Essentially, the AI "learns" the relationship between <strong>topography</strong> (water movement), <strong>human activity</strong> (extraction), and <strong>geology</strong> (storage) to estimate levels in villages where no physical sensors are installed.</p>
          </div>
        </div>
      </div>
  );

  if (isPage) return content;

  return (
    <div className="methodology-overlay" onClick={onClose}>
      <div className="methodology-modal" onClick={e => e.stopPropagation()}>
        {content}
      </div>
    </div>
  );
}
