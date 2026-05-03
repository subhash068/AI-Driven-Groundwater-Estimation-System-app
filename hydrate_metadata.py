import geopandas as gpd
import pandas as pd
import os

def hydrate_metadata(target_path, source_path):
    if not os.path.exists(target_path) or not os.path.exists(source_path):
        print(f"Skipping {target_path} - files not found.")
        return

    print(f"Hydrating {target_path} from {source_path}...")
    target_gdf = gpd.read_file(target_path)
    source_gdf = gpd.read_file(source_path)

    # Ensure village_id is numeric
    target_gdf['village_id'] = pd.to_numeric(target_gdf['village_id'], errors='coerce')
    source_gdf['village_id'] = pd.to_numeric(source_gdf['village_id'], errors='coerce')

    # Drop existing district/mandal if they are all NaNs or missing
    cols_to_sync = ['district', 'mandal', 'state']
    for col in cols_to_sync:
        if col in target_gdf.columns:
            if target_gdf[col].isna().all() or (target_gdf[col] == 'nan').all() or (target_gdf[col] == 'Unknown').all():
                target_gdf = target_gdf.drop(columns=[col])

    # Merge
    metadata = source_gdf[['village_id', 'district', 'mandal', 'state']].drop_duplicates('village_id')
    merged = target_gdf.merge(metadata, on='village_id', how='left')

    # Fill NaNs from merge
    for col in cols_to_sync:
        if col in merged.columns:
            merged[col] = merged[col].fillna('Unknown')

    print(f"Saving {target_path}...")
    merged.to_file(target_path, driver='GeoJSON')
    print("Done.")

if __name__ == "__main__":
    source = 'frontend/public/data/villages.geojson'
    hydrate_metadata('output/map_data_predictions.geojson', source)
    hydrate_metadata('frontend/public/data/map_data_predictions.geojson', source)
