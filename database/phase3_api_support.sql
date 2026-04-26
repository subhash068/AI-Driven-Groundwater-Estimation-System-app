CREATE SCHEMA IF NOT EXISTS groundwater;

CREATE TABLE IF NOT EXISTS groundwater.village_estimates (
    estimate_id BIGSERIAL PRIMARY KEY,
    village_id BIGINT NOT NULL REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    estimated_groundwater_depth NUMERIC(10, 3) NOT NULL,
    confidence_score NUMERIC(5, 2) NOT NULL,
    anomaly_flag BOOLEAN NOT NULL DEFAULT FALSE,
    draft_index NUMERIC(6, 4) NOT NULL DEFAULT 0.5,
    model_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groundwater.village_forecasts (
    forecast_id BIGSERIAL PRIMARY KEY,
    village_id BIGINT NOT NULL REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    forecast_date DATE NOT NULL,
    predicted_groundwater_depth NUMERIC(10, 3) NOT NULL,
    predicted_lower NUMERIC(10, 3),
    predicted_upper NUMERIC(10, 3),
    model_name TEXT NOT NULL DEFAULT 'prophet',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (village_id, forecast_date, model_name)
);

CREATE TABLE IF NOT EXISTS groundwater.village_anomalies (
    anomaly_id BIGSERIAL PRIMARY KEY,
    village_id BIGINT NOT NULL REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    anomaly_type TEXT NOT NULL,
    anomaly_score NUMERIC(8, 4),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_village_estimates_village_time
    ON groundwater.village_estimates (village_id, model_run_at DESC);

CREATE INDEX IF NOT EXISTS idx_village_forecasts_village_date
    ON groundwater.village_forecasts (village_id, forecast_date);

CREATE TABLE IF NOT EXISTS groundwater.village_seasonal_norms (
    seasonal_norm_id BIGSERIAL PRIMARY KEY,
    village_id BIGINT NOT NULL REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    month_num INTEGER NOT NULL CHECK (month_num BETWEEN 1 AND 12),
    norm_depth NUMERIC(10, 3) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (village_id, month_num)
);

CREATE INDEX IF NOT EXISTS idx_village_anomalies_village_time
    ON groundwater.village_anomalies (village_id, detected_at DESC);
