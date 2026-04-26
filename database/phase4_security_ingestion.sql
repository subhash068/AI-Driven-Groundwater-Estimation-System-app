CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;

CREATE SCHEMA IF NOT EXISTS groundwater;

CREATE TABLE IF NOT EXISTS groundwater.app_users (
    user_id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'engineer', 'admin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groundwater.village_advisories (
    advisory_id BIGSERIAL PRIMARY KEY,
    village_id BIGINT NOT NULL REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    advisory_level TEXT NOT NULL CHECK (advisory_level IN ('safe', 'warning', 'critical')),
    advisory_text TEXT NOT NULL,
    language_code TEXT NOT NULL DEFAULT 'en',
    channel TEXT NOT NULL DEFAULT 'sms',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_village_advisories_village_time
    ON groundwater.village_advisories (village_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS groundwater.raster_products (
    raster_id BIGSERIAL PRIMARY KEY,
    product_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    observed_date DATE NOT NULL,
    village_id BIGINT REFERENCES groundwater.villages(village_id) ON DELETE SET NULL,
    rast RASTER NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raster_products_observed_date
    ON groundwater.raster_products (observed_date);

CREATE TABLE IF NOT EXISTS groundwater.ingestion_runs (
    run_id BIGSERIAL PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    source_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    records_ingested INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
