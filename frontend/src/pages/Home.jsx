import React from "react";
import { HeroSection } from "../components/home/HeroSection";
import { MapPreview } from "../components/home/MapPreview";
import { InsightsCards } from "../components/home/InsightsCards";
import { HowItWorks } from "../components/home/HowItWorks";
import { Features } from "../components/home/Features";
import { Validation } from "../components/home/Validation";
import { CTA } from "../components/home/CTA";
import { ImpactSection } from "../components/home/ImpactSection";
import { Footer } from "../components/home/Footer";
import { useHomepageStats } from "../hooks/useHomepageStats";
import "./Home.css";

export function Home({ onEnterDashboard, villages }) {
  const { stats, loading, error } = useHomepageStats();

  return (
    <div className="home-page">
      <header className="home-header">
        <img src="/ap_banner.png" alt="Government Header" className="home-header-banner" />
        <h1 className="home-header-title">AI-Driven Groundwater Estimation System</h1>
      </header>
      <HeroSection onEnterDashboard={onEnterDashboard} stats={stats} />
      <MapPreview villages={villages} stats={stats} />
      <InsightsCards stats={stats} loading={loading} error={error} />
      <HowItWorks />
      <Features />
      <Validation stats={stats} loading={loading} error={error} />
      <CTA onEnterDashboard={onEnterDashboard} />
      <ImpactSection />
      <Footer />
    </div>
  );
}
