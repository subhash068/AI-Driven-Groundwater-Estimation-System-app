import geopandas as gpd
import pandas as pd

def check_duplicates():
    geojson_path = 'frontend/public/data/map_data_predictions.geojson'
    gdf = gpd.read_file(geojson_path)
    
    print(f"Total features: {len(gdf)}")
    
    # Check for duplicate village_id
    id_counts = gdf['village_id'].value_counts()
    duplicates_id = id_counts[id_counts > 1]
    
    if not duplicates_id.empty:
        print("\nDuplicate village_ids found:")
        print(duplicates_id)
        # Show some examples
        for vid in duplicates_id.index[:5]:
            print(f"\nExample for village_id {vid}:")
            print(gdf[gdf['village_id'] == vid][['village_name', 'mandal', 'district']])
    else:
        print("\nNo duplicate village_ids found.")
        
    # Check for duplicate village_name + mandal (since names might repeat across mandals)
    gdf['unique_key'] = gdf['village_name'].astype(str) + "_" + gdf['mandal'].astype(str)
    key_counts = gdf['unique_key'].value_counts()
    duplicates_key = key_counts[key_counts > 1]
    
    if not duplicates_key.empty:
        print("\nDuplicate Village+Mandal names found:")
        print(duplicates_key.head(10))
    else:
        print("\nNo duplicate Village+Mandal names found.")

    # Check for IDs that might be mixed up
    # e.g. same name but different IDs
    name_to_ids = gdf.groupby('village_name')['village_id'].unique()
    multiple_ids = name_to_ids[name_to_ids.apply(len) > 1]
    if not multiple_ids.empty:
        print("\nVillages with same name but different IDs:")
        for name, ids in multiple_ids.head(5).items():
            print(f"{name}: {ids}")

if __name__ == "__main__":
    check_duplicates()
