import geopandas as gpd
import pandas as pd

gdf = gpd.read_file('frontend/public/data/map_data_predictions.geojson')
print(f"Total: {len(gdf)}")
print(f"Has groundwater_level (observed): {gdf['groundwater_level'].notna().sum()}")
if 'predicted_groundwater_level' in gdf.columns:
    print(f"Has predicted_groundwater_level: {gdf['predicted_groundwater_level'].notna().sum()}")
else:
    print("Column 'predicted_groundwater_level' NOT found")

if 'estimated_depth' in gdf.columns:
    print(f"Has estimated_depth: {gdf['estimated_depth'].notna().sum()}")
