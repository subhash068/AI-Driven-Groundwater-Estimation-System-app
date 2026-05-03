import geopandas as gpd
import pandas as pd
import os
import json

def normalize_name(s):
    if not s or pd.isna(s): return ""
    return str(s).strip().upper()

def reindex_villages():
    data_dir = 'frontend/public/data'
    master_file = os.path.join(data_dir, 'map_data_predictions.geojson')
    
    print(f"Loading master registry from {master_file}...")
    master_gdf = gpd.read_file(master_file)
    
    # Create master mapping: (district, mandal, village_name) -> village_id
    master_map = {}
    for _, row in master_gdf.iterrows():
        key = (
            normalize_name(row.get('district', '')),
            normalize_name(row.get('mandal', '')),
            normalize_name(row.get('village_name', ''))
        )
        master_map[key] = int(row['village_id'])
    
    print(f"Master registry contains {len(master_map)} unique village definitions.")

    # Files to re-index
    targets = [
        'villages.geojson',
        'village_boundaries.geojson',
        'villages_with_sensors.geojson'
    ]
    
    for target in targets:
        path = os.path.join(data_dir, target)
        if not os.path.exists(path):
            print(f"Skipping {target} (not found)")
            continue
            
        print(f"Re-indexing {target}...")
        gdf = gpd.read_file(path)
        
        updates = 0
        mismatches = 0
        
        def update_id(row):
            nonlocal updates, mismatches
            key = (
                normalize_name(row.get('district', row.get('District', ''))),
                normalize_name(row.get('mandal', row.get('Mandal', ''))),
                normalize_name(row.get('village_name', row.get('Village_Name', row.get('VILLAGE', ''))))
            )
            
            new_id = master_map.get(key)
            if new_id is not None:
                if int(row.get('village_id', -1)) != new_id:
                    updates += 1
                return new_id
            else:
                mismatches += 1
                return row.get('village_id') # Keep original if not in master

        if 'village_id' in gdf.columns:
            gdf['village_id'] = gdf.apply(update_id, axis=1)
        elif 'ID' in gdf.columns:
            gdf['village_id'] = gdf.apply(update_id, axis=1)
        else:
            gdf['village_id'] = gdf.apply(update_id, axis=1)

        print(f"  Updates: {updates}, Mismatches: {mismatches}")
        
        # Ensure village_id is integer where possible
        gdf['village_id'] = pd.to_numeric(gdf['village_id'], errors='coerce').fillna(0).astype(int)
        
        # Save back
        gdf.to_file(path, driver='GeoJSON')
        print(f"  Saved {target}")

if __name__ == "__main__":
    reindex_villages()
