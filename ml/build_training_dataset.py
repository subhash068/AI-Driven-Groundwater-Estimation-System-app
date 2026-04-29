import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


DEFAULT_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5432/groundwater"


SQL = """
WITH nearest_weighted AS (
    SELECT
        v.village_id,
        -- Use 1/d^2 weighting as requested for better spatial sensitivity
        SUM(p.current_depth * (1.0 / (NULLIF(ST_Distance(ST_Transform(ST_Centroid(v.geom), 3857), ST_Transform(p.geom, 3857)), 0)^2 + 1e-6))) / 
        SUM(1.0 / (NULLIF(ST_Distance(ST_Transform(ST_Centroid(v.geom), 3857), ST_Transform(p.geom, 3857)), 0)^2 + 1e-6)) AS weighted_sensor_depth
    FROM groundwater.villages v
    CROSS JOIN LATERAL (
        SELECT current_depth, geom
        FROM groundwater.piezometers
        ORDER BY v.geom <-> geom
        LIMIT 5
    ) p
    GROUP BY v.village_id
)
SELECT
    m.village_id,
    m.rainfall_variability,
    m.elevation_dem,
    m.slope_deg,
    m.proximity_rivers_tanks_km,
    m.soil_permeability,
    m.rainfall_lag_1m,
    m.lulc_code,
    m.geomorphology_class,
    -- Seasonal features
    EXTRACT(MONTH FROM NOW()) AS month_num,
    CASE WHEN EXTRACT(MONTH FROM NOW()) BETWEEN 6 AND 9 THEN 1 ELSE 0 END AS is_monsoon,
    COALESCE(m.depth_to_water_level, nw.weighted_sensor_depth) AS depth_to_water_level,
    m.has_sensor,
    COALESCE(va.is_anomaly_label, 0) AS is_anomaly_label
FROM groundwater.ml_training_view m
LEFT JOIN nearest_weighted nw ON nw.village_id = m.village_id
LEFT JOIN (
    SELECT village_id, 1 AS is_anomaly_label
    FROM groundwater.village_anomalies
    GROUP BY village_id
) va ON va.village_id = m.village_id;
"""


def run(dsn: str, out_path: Path) -> None:
    engine = create_engine(dsn)
    df = pd.read_sql(SQL, engine)
    
    # In a real spatio-temporal scenario, we would have multiple rows per village
    # for different time steps. For this POC, we derive seasonal features from current time.
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".csv":
        df.to_csv(out_path, index=False)
    else:
        df.to_parquet(out_path, index=False)
    print(f"Saved training dataset: {out_path} ({len(df)} rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ML training dataset with advanced hydro-geological features")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="SQLAlchemy DSN")
    parser.add_argument("--out", type=Path, required=True, help="Output file (.csv or .parquet)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.dsn, args.out)
