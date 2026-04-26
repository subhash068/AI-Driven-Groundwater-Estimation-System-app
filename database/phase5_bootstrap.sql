CREATE SCHEMA IF NOT EXISTS groundwater;

ALTER TABLE groundwater.villages
    ADD COLUMN IF NOT EXISTS village_external_id TEXT,
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

ALTER TABLE groundwater.village_features
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

ALTER TABLE groundwater.village_estimates
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS data_version TEXT,
    ADD COLUMN IF NOT EXISTS risk_level TEXT;

ALTER TABLE groundwater.village_forecasts
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

ALTER TABLE groundwater.village_anomalies
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

ALTER TABLE groundwater.village_advisories
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

ALTER TABLE groundwater.piezometers
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

ALTER TABLE groundwater.hydrogeology
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS data_version TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_villages_external_id
    ON groundwater.villages (village_external_id)
    WHERE village_external_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_village_estimates_village_data_version
    ON groundwater.village_estimates (village_id, data_version);

CREATE UNIQUE INDEX IF NOT EXISTS uq_village_anomalies_village_data_version_type
    ON groundwater.village_anomalies (village_id, data_version, anomaly_type);

CREATE UNIQUE INDEX IF NOT EXISTS uq_village_advisories_village_data_version_level
    ON groundwater.village_advisories (village_id, data_version, advisory_level);

CREATE INDEX IF NOT EXISTS idx_village_estimates_village_id
    ON groundwater.village_estimates (village_id);

CREATE INDEX IF NOT EXISTS idx_village_estimates_risk_level
    ON groundwater.village_estimates (risk_level);

CREATE INDEX IF NOT EXISTS idx_villages_geom_gist
    ON groundwater.villages USING GIST (geom);

CREATE TABLE IF NOT EXISTS groundwater.bootstrap_logs (
    bootstrap_log_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL,
    error TEXT
);

CREATE MATERIALIZED VIEW IF NOT EXISTS groundwater.village_dashboard AS
WITH latest_estimate AS (
    SELECT DISTINCT ON (ve.village_id)
        ve.village_id,
        ve.estimated_groundwater_depth,
        ve.confidence_score,
        ve.draft_index,
        ve.anomaly_flag,
        ve.risk_level,
        ve.model_run_at
    FROM groundwater.village_estimates ve
    ORDER BY ve.village_id, ve.model_run_at DESC
),
forecast_agg AS (
    SELECT
        vf.village_id,
        json_agg(
            json_build_object(
                'forecast_date', vf.forecast_date,
                'predicted_groundwater_depth', vf.predicted_groundwater_depth,
                'predicted_lower', vf.predicted_lower,
                'predicted_upper', vf.predicted_upper,
                'model_name', vf.model_name
            ) ORDER BY vf.forecast_date
        ) AS forecast_3_month
    FROM groundwater.village_forecasts vf
    GROUP BY vf.village_id
),
anomaly_agg AS (
    SELECT
        va.village_id,
        COUNT(*) FILTER (WHERE va.detected_at >= NOW() - INTERVAL '90 days') AS anomaly_count_90d,
        MAX(va.detected_at) AS last_anomaly_at,
        MAX(va.anomaly_score) AS max_anomaly_score
    FROM groundwater.village_anomalies va
    GROUP BY va.village_id
)
SELECT
    v.village_id,
    v.village_external_id,
    v.village_name,
    v.district,
    v.mandal,
    ST_AsGeoJSON(v.geom)::json AS geometry,
    le.estimated_groundwater_depth,
    le.confidence_score,
    le.draft_index,
    le.anomaly_flag,
    COALESCE(le.risk_level, 'warning') AS risk_level,
    COALESCE(fa.forecast_3_month, '[]'::json) AS forecast_3_month,
    COALESCE(aa.anomaly_count_90d, 0) AS anomaly_count_90d,
    aa.last_anomaly_at,
    aa.max_anomaly_score,
    le.model_run_at
FROM groundwater.villages v
LEFT JOIN latest_estimate le ON le.village_id = v.village_id
LEFT JOIN forecast_agg fa ON fa.village_id = v.village_id
LEFT JOIN anomaly_agg aa ON aa.village_id = v.village_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_village_dashboard_village_id
    ON groundwater.village_dashboard (village_id);
