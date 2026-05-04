import React from "react";

export function Footer() {
  const currentYear = new Date().getFullYear();
  
  return (
    <footer className="home-footer">
      <div className="home-footer-content">
        <div className="footer-brand">
          <div className="footer-logo">
            <span className="logo-icon">💧</span>
            <h2>AI-Driven Groundwater Estimation System</h2>
          </div>
          <p className="footer-description">
            Empowering sustainable water management through geospatial intelligence, 
            machine learning, and precise district-level forecasting.
          </p>
        </div>
        
        <div className="footer-links-group">
          <div className="footer-links">
            <h3>Quick Links</h3>
            <a href="#map-preview">Groundwater Map</a>
            <a href="#insights">Key Insights</a>
            <a href="#validation">Model Validation</a>
          </div>
          
          <div className="footer-links">
            <h3>Resources</h3>
            <a href="#">Methodology</a>
            <a href="#">API Documentation</a>
            <a href="#">Data Sources</a>
          </div>
        </div>
      </div>
      
      <div className="home-footer-bottom">
        <p>&copy; {currentYear} Government of Andhra Pradesh. All rights reserved.</p>
        <div className="footer-legal">
          <a href="#">Privacy Policy</a>
          <a href="#">Terms of Service</a>
        </div>
      </div>
    </footer>
  );
}
