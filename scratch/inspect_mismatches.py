import geopandas as gpd
import pandas as pd
import os

def normalize_name(s):
    if not s or pd.isna(s): return ""
    return str(s).strip().upper()

def inspect_mismatches():
    data_dir = 'frontend/public/data'
    master_file = os.path.join(data_dir, 'map_data_predictions.geojson')
    target_file = os.path.join(data_dir, 'villages.geojson')
    
    master_gdf = gpd.read_file(master_file)
    target_gdf = gpd.read_file(target_file)
    
    master_keys = set()
    for _, row in master_gdf.iterrows():
        key = (
            normalize_name(row.get('district', '')),
            normalize_name(row.get('mandal', '')),
            normalize_name(row.get('village_name', ''))
        )
        master_keys.add(key)
        
    print(f"Master keys: {len(master_keys)}")
    
    mismatches = []
    for _, row in target_gdf.iterrows():
        key = (
            normalize_name(row.get('district', row.get('District', ''))),
            normalize_name(row.get('mandal', row.get('Mandal', ''))),
            normalize_name(row.get('village_name', row.get('Village_Name', '')))
        )
        if key not in master_keys:
            mismatches.append(key)
            
    print(f"Target mismatches: {len(mismatches)}")
    print("Sample mismatches:")
    for m in mismatches[:10]:
        print(m)
        
    # Check if maybe mandals are different?
    print("\nChecking if village names match but mandals differ...")
    master_villages = {normalize_name(row.get('village_name', '')): normalize_name(row.get('mandal', '')) for _, row in master_gdf.iterrows()}
    
    for m in mismatches[:10]:
        vname = m[2]
        if vname in master_villages:
            print(f"Village '{vname}' found in master, but with mandal '{master_villages[vname]}' instead of '{m[1]}'")

if __name__ == "__main__":
    inspect_mismatches()
