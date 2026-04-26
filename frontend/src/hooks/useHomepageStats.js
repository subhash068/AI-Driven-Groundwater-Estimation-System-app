import { useEffect, useState } from "react";

const EMPTY_STATS = {
  villages: null,
  avg_trend_slope: null,
  high_risk_count: null,
  anomaly_count: null,
  district_aggregation: {
    districts: [],
    comparison_insight: null
  },
  model: { r2: null, rmse: null, mae: null },
  snapshot: { sample_village: null, actual_last_month: null, predicted_gwl: null },
  meta: { generated_at: null }
};

export function useHomepageStats() {
  const [stats, setStats] = useState(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        setLoading(true);
        const response = await fetch("/data/homepage_stats.json", {
          headers: { Accept: "application/json" }
        });
        if (!response.ok) {
          throw new Error("homepage_stats.json unavailable");
        }
        const data = await response.json();
        if (!active) return;
        setStats({
          ...EMPTY_STATS,
          ...data,
          district_aggregation: {
            ...EMPTY_STATS.district_aggregation,
            ...(data?.district_aggregation || {}),
            districts: Array.isArray(data?.district_aggregation?.districts)
              ? data.district_aggregation.districts
              : []
          },
          model: { ...EMPTY_STATS.model, ...(data?.model || {}) },
          snapshot: { ...EMPTY_STATS.snapshot, ...(data?.snapshot || {}) },
          meta: { ...EMPTY_STATS.meta, ...(data?.meta || {}) }
        });
        setError(null);
      } catch (err) {
        if (!active) return;
        setStats(EMPTY_STATS);
        setError(err?.message || "Failed to load homepage stats");
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  return { stats, loading, error };
}
