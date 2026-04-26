CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS groundwater;

CREATE TABLE IF NOT EXISTS groundwater.villages (
    village_id BIGSERIAL PRIMARY KEY,
    village_name TEXT NOT NULL,
    census_id VARCHAR(32) UNIQUE NOT NULL,
    district TEXT NOT NULL,
    mandal TEXT NOT NULL,
    population INTEGER NOT NULL CHECK (population >= 0),
    geom GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groundwater.piezometers (
    piezometer_id BIGSERIAL PRIMARY KEY,
    station_id VARCHAR(32) UNIQUE NOT NULL,
    current_depth NUMERIC(10, 3) NOT NULL CHECK (current_depth >= 0),
    status TEXT NOT NULL DEFAULT 'active',
    geom GEOMETRY(POINT, 4326) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groundwater.hydrogeology (
    hydrogeology_id BIGSERIAL PRIMARY KEY,
    village_id BIGINT NOT NULL REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    soil_type TEXT NOT NULL,
    rock_formation TEXT NOT NULL,
    permeability NUMERIC(10, 5) NOT NULL CHECK (permeability >= 0),
    porosity NUMERIC(10, 5),
    transmissivity NUMERIC(12, 5),
    aquifer_depth_m NUMERIC(10, 3),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (village_id)
);

CREATE TABLE IF NOT EXISTS groundwater.rainfall_history (
    rainfall_id BIGSERIAL PRIMARY KEY,
    grid_cell_id VARCHAR(64) NOT NULL,
    observed_date DATE NOT NULL,
    rainfall_mm NUMERIC(10, 3) NOT NULL CHECK (rainfall_mm >= 0),
    source TEXT DEFAULT 'IMD',
    geom GEOMETRY(POLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (grid_cell_id, observed_date)
);

CREATE INDEX IF NOT EXISTS idx_villages_geom_gist
    ON groundwater.villages
    USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_piezometers_geom_gist
    ON groundwater.piezometers
    USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_rainfall_geom_gist
    ON groundwater.rainfall_history
    USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_rainfall_observed_date
    ON groundwater.rainfall_history (observed_date);

CREATE INDEX IF NOT EXISTS idx_hydrogeology_permeability
    ON groundwater.hydrogeology (permeability);

CREATE OR REPLACE FUNCTION groundwater.find_nearest_piezometers(
    p_village_id BIGINT,
    p_limit INTEGER DEFAULT 5
)
RETURNS TABLE (
    village_id BIGINT,
    piezometer_id BIGINT,
    station_id VARCHAR(32),
    distance_meters DOUBLE PRECISION,
    inverse_distance_weight DOUBLE PRECISION,
    normalized_weight DOUBLE PRECISION,
    weighted_distance DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_geom GEOMETRY;
BEGIN
    SELECT geom INTO v_geom
    FROM groundwater.villages
    WHERE villages.village_id = p_village_id;

    IF v_geom IS NULL THEN
        RAISE EXCEPTION 'Village ID % not found', p_village_id;
    END IF;

    RETURN QUERY
    WITH nearest AS (
        SELECT
            p.piezometer_id,
            p.station_id,
            ST_Distance(
                ST_Transform(ST_Centroid(v_geom), 3857),
                ST_Transform(p.geom, 3857)
            ) AS distance_meters
        FROM groundwater.piezometers p
        ORDER BY v_geom <-> p.geom
        LIMIT p_limit
    ),
    weighted AS (
        SELECT
            n.piezometer_id,
            n.station_id,
            n.distance_meters,
            CASE
                WHEN n.distance_meters = 0 THEN 1.0
                ELSE 1.0 / n.distance_meters
            END AS inverse_distance_weight
        FROM nearest n
    ),
    normalized AS (
        SELECT
            w.*,
            w.inverse_distance_weight / SUM(w.inverse_distance_weight) OVER () AS normalized_weight
        FROM weighted w
    )
    SELECT
        p_village_id,
        n.piezometer_id,
        n.station_id,
        n.distance_meters,
        n.inverse_distance_weight,
        n.normalized_weight,
        n.distance_meters * n.normalized_weight AS weighted_distance
    FROM normalized n
    ORDER BY n.distance_meters;
END;
$$;
