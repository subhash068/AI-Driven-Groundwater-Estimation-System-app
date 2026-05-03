import geopandas as gpd
import pandas as pd
import numpy as np

def verify_data(path):
    print(f"\n--- Verifying: {path} ---")
    try:
        gdf = gpd.read_file(path)
    except Exception as e:
        print(f"Error loading file: {e}")
        return

    total = len(gdf)
    missing_gwl = gdf['groundwater_level'].isna().sum()
    zero_gwl = (gdf['groundwater_level'] == 0).sum()
    missing_source = gdf['data_source'].isna().sum() if 'data_source' in gdf.columns else "COLUMN MISSING"
    
    # Check for NTR/Krishna coverage
    districts = gdf['district'].unique().tolist() if 'district' in gdf.columns else []
    if not districts and 'District' in gdf.columns:
        districts = gdf['District'].unique().tolist()
    
    print(f"Total Villages: {total}")
    print(f"Missing (NaN) Groundwater Levels: {missing_gwl}")
    print(f"Zero (0.0) Groundwater Levels: {zero_gwl}")
    print(f"Missing Data Source: {missing_source}")
    print(f"Districts Found: {districts}")
    
    if missing_gwl == 0:
        print("SUCCESS: No NaN groundwater levels found.")
    else:
        print("FAILURE: Some villages still have NaN groundwater levels.")


if __name__ == "__main__":
    verify_data('output/map_data_predictions.geojson')
    verify_data('frontend/public/data/map_data_predictions.geojson')
