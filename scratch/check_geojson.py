import geopandas as gpd
import pandas as pd

gdf = gpd.read_file('frontend/public/data/map_data_predictions.geojson')
print(f"Total villages in map_data_predictions.geojson: {len(gdf)}")
if 'groundwater_level' in gdf.columns:
    print(f"Villages with groundwater_level: {gdf['groundwater_level'].notna().sum()}")
else:
    # Check other possible columns
    for col in ['estimated_depth', 'predicted_groundwater_level']:
        if col in gdf.columns:
            print(f"Villages with {col}: {gdf[col].notna().sum()}")

# Check for district/mandal counts
if 'district' in gdf.columns:
    print(f"Districts: {gdf['district'].nunique()}")
if 'mandal' in gdf.columns:
    print(f"Mandals: {gdf['mandal'].nunique()}")
