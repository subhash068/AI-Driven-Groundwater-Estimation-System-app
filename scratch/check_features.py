import geopandas as gpd
import pandas as pd

file_path = 'data/processed/villages_with_features_v2.geojson'
gdf = gpd.read_file(file_path)
print(f"Total villages in {file_path}: {len(gdf)}")
if 'has_sensor' in gdf.columns:
    print(f"Villages with has_sensor=1: {gdf['has_sensor'].sum()}")
else:
    print("Column 'has_sensor' not found.")

print("Columns:", gdf.columns.tolist())
