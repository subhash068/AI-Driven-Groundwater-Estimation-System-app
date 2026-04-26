import React from "react";
import { HeroSection } from "../components/home/HeroSection";
import { MapPreview } from "../components/home/MapPreview";
import { InsightsCards } from "../components/home/InsightsCards";
import { HowItWorks } from "../components/home/HowItWorks";
import { Features } from "../components/home/Features";
import { Validation } from "../components/home/Validation";
import { CTA } from "../components/home/CTA";
import { ImpactSection } from "../components/home/ImpactSection";
import { useHomepageStats } from "../hooks/useHomepageStats";
import "./Home.css";

export function Home({ onEnterDashboard, villages }) {
  const { stats, loading, error } = useHomepageStats();

  return (
    <div className="home-page">
      <HeroSection onEnterDashboard={onEnterDashboard} stats={stats} />
      <MapPreview villages={villages} stats={stats} />
      <InsightsCards stats={stats} loading={loading} error={error} />
      <HowItWorks />
      <Features />
      <Validation stats={stats} loading={loading} error={error} />
      <CTA onEnterDashboard={onEnterDashboard} />
      <ImpactSection />
    </div>
  );
}
