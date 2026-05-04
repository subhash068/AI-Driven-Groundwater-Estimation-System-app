import os
import json
import asyncio
import pandas as pd
import geopandas as gpd
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
DB_DSN = os.getenv("DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/groundwater")

engine = create_async_engine(DB_DSN)

async def migrate():
    print("Starting database migration from JSON/GeoJSON...")
    
    # 1. Load GeoJSON for Village Boundaries and basic props
    geojson_path = DATA_DIR / "map_data_predictions.geojson"
    if not geojson_path.exists():
        geojson_path = DATA_DIR / "villages.geojson"
        
    print(f"Loading GeoJSON from {geojson_path}...")
    gdf = gpd.read_file(geojson_path)
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)
        
    # Ensure village_id is present
    if "village_id" not in gdf.columns:
        if "Village_ID" in gdf.columns:
            gdf["village_id"] = gdf["Village_ID"]
        else:
            gdf["village_id"] = range(1, len(gdf) + 1)
            
    gdf["village_id"] = pd.to_numeric(gdf["village_id"], errors="coerce").fillna(-1).astype(int)
    gdf = gdf[gdf["village_id"] > 0]

    async with engine.connect() as conn:
        print("Cleaning up existing data...")
        # Optional: await conn.execute(text("TRUNCATE groundwater.villages RESTART IDENTITY CASCADE"))
        # await conn.commit()

        print(f"Ingesting {len(gdf)} villages...")
        success_count = 0
        error_count = 0

        for _, row in gdf.iterrows():
            try:
                # Use a separate transaction for each village
                async with conn.begin():
                    # Insert Village
                    geom_wkt = row.geometry.wkt
                    await conn.execute(
                        text("""
                            INSERT INTO groundwater.villages (village_id, village_name, census_id, district, mandal, population, geom)
                            VALUES (:vid, :vname, :cid, :dist, :mand, :pop, ST_GeomFromText(:geom, 4326))
                            ON CONFLICT (village_id) DO UPDATE SET
                                village_name = EXCLUDED.village_name,
                                district = EXCLUDED.district,
                                mandal = EXCLUDED.mandal,
                                geom = EXCLUDED.geom
                        """),
                        {
                            "vid": int(row["village_id"]),
                            "vname": str(row.get("village_name", row.get("Village_Name", "Unknown"))),
                            "cid": str(row.get("census_id", row.get("CENSUS_ID", f"CID_{row['village_id']}"))),
                            "dist": str(row.get("district", row.get("District", "Unknown"))),
                            "mand": str(row.get("mandal", row.get("Mandal", "Unknown"))),
                            "pop": int(row.get("population", 0)),
                            "geom": geom_wkt
                        }
                    )
                    
                    # Insert Estimate
                    depth = row.get("predicted_groundwater_level", row.get("groundwater_level"))
                    if depth is not None and not pd.isna(depth):
                        await conn.execute(
                            text("""
                                INSERT INTO groundwater.village_estimates (village_id, estimated_groundwater_depth, confidence_score, anomaly_flag, risk_level)
                                VALUES (:vid, :depth, :conf, :anomaly, :risk)
                                ON CONFLICT (village_id) DO UPDATE SET
                                    estimated_groundwater_depth = EXCLUDED.estimated_groundwater_depth,
                                    confidence_score = EXCLUDED.confidence_score,
                                    anomaly_flag = EXCLUDED.anomaly_flag,
                                    risk_level = EXCLUDED.risk_level
                            """),
                            {
                                "vid": int(row["village_id"]),
                                "depth": float(depth),
                                "conf": float(row.get("confidence", 0.8)),
                                "anomaly": bool(row.get("is_anomaly", False)),
                                "risk": str(row.get("risk_level", "safe")).lower()
                            }
                        )
                    
                    # Insert Hydrogeology (Soil/Rock)
                    soil = row.get("soil", row.get("Soil_Type"))
                    if soil:
                        await conn.execute(
                            text("""
                                INSERT INTO groundwater.hydrogeology (village_id, soil_type, rock_formation, permeability)
                                VALUES (:vid, :soil, :rock, :perm)
                                ON CONFLICT (village_id) DO UPDATE SET
                                    soil_type = EXCLUDED.soil_type,
                                    rock_formation = EXCLUDED.rock_formation
                            """),
                            {
                                "vid": int(row["village_id"]),
                                "soil": str(soil),
                                "rock": str(row.get("rock_formation", "Unknown")),
                                "perm": float(row.get("permeability", 0.5))
                            }
                        )
                success_count += 1
                if success_count % 50 == 0:
                    print(f"Progress: {success_count} villages imported...")

            except Exception as e:
                error_count += 1
                # print(f"Error inserting village {row.get('village_id')}: {e}")

        print(f"Ingestion complete. Success: {success_count}, Errors: {error_count}")
        
        print("Refreshing materialized views...")
        try:
            async with conn.begin():
                await conn.execute(text("REFRESH MATERIALIZED VIEW groundwater.village_dashboard"))
            print("Dashboard view refreshed successfully.")
        except Exception as e:
            print(f"Failed to refresh view: {e}")

    print("Migration finished!")

if __name__ == "__main__":
    asyncio.run(migrate())
