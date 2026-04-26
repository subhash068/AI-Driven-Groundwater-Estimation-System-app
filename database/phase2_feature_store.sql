CREATE SCHEMA IF NOT EXISTS groundwater;

CREATE TABLE IF NOT EXISTS groundwater.village_features (
    village_id BIGINT PRIMARY KEY REFERENCES groundwater.villages(village_id) ON DELETE CASCADE,
    elevation_dem NUMERIC(10, 3),
    slope_deg NUMERIC(8, 3),
    proximity_rivers_tanks_km NUMERIC(10, 3),
    rainfall_variability NUMERIC(10, 3),
    rainfall_lag_1m NUMERIC(10, 3),
    lulc_code INTEGER,
    geomorphology_class TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_village_features_geomorphology
    ON groundwater.village_features (geomorphology_class);

CREATE OR REPLACE VIEW groundwater.ml_training_view AS
SELECT
    v.village_id,
    vf.elevation_dem,
    vf.slope_deg,
    vf.proximity_rivers_tanks_km,
    vf.rainfall_variability,
    vf.rainfall_lag_1m,
    vf.lulc_code,
    h.permeability AS soil_permeability,
    ve.estimated_groundwater_depth AS depth_to_water_level,
    CASE WHEN p.piezometer_id IS NOT NULL THEN 1 ELSE 0 END AS has_sensor
FROM groundwater.villages v
LEFT JOIN groundwater.village_features vf ON vf.village_id = v.village_id
LEFT JOIN groundwater.hydrogeology h ON h.village_id = v.village_id
LEFT JOIN LATERAL (
    SELECT pz.piezometer_id
    FROM groundwater.piezometers pz
    WHERE ST_DWithin(
        ST_Transform(pz.geom, 3857),
        ST_Transform(ST_Centroid(v.geom), 3857),
        10000
    )
    ORDER BY pz.geom <-> ST_Centroid(v.geom)
    LIMIT 1
) p ON TRUE
LEFT JOIN groundwater.village_estimates ve ON ve.village_id = v.village_id;
