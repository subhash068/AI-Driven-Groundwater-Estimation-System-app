import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


DEFAULT_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5432/groundwater"


SQL = """
WITH nearest_weighted AS (
    SELECT
        v.village_id,
        AVG(n.current_depth * n.normalized_weight) AS weighted_sensor_depth
    FROM groundwater.villages v
    JOIN LATERAL groundwater.find_nearest_piezometers(v.village_id, 5) n ON TRUE
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".csv":
        df.to_csv(out_path, index=False)
    else:
        df.to_parquet(out_path, index=False)
    print(f"Saved training dataset: {out_path} ({len(df)} rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ML training dataset from PostGIS spatial joins")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="SQLAlchemy DSN")
    parser.add_argument("--out", type=Path, required=True, help="Output file (.csv or .parquet)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.dsn, args.out)
