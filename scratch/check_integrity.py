import geopandas as gpd
import pandas as pd
import os

def check_village_id_integrity():
    data_dir = 'frontend/public/data'
    files = [
        'map_data_predictions.geojson',
        'villages.geojson',
        'village_boundaries.geojson',
        'map_data_predictions_ntr.geojson'
    ]
    
    all_data = []
    
    for f in files:
        path = os.path.join(data_dir, f)
        if not os.path.exists(path):
            continue
        print(f"Loading {f}...")
        try:
            gdf = gpd.read_file(path)
            if 'village_id' in gdf.columns:
                gdf['source_file'] = f
                # Keep relevant columns for comparison
                cols = ['village_id', 'village_name', 'mandal', 'district', 'source_file']
                available_cols = [c for c in cols if c in gdf.columns]
                all_data.append(gdf[available_cols])
        except Exception as e:
            print(f"Error loading {f}: {e}")
            
    if not all_data:
        print("No data found.")
        return
        
    df = pd.concat(all_data, ignore_index=True)
    
    # 1. Check for duplicate village_id across different files with DIFFERENT names
    print("\nChecking for village_id collisions (Same ID, Different Name/Mandal):")
    id_groups = df.groupby('village_id')
    for vid, group in id_groups:
        unique_villages = group.drop_duplicates(subset=['village_name', 'mandal'])
        if len(unique_villages) > 1:
            print(f"\nCollision for ID {vid}:")
            print(unique_villages)

    # 2. Check for same village name with different IDs across files
    print("\nChecking for name collisions (Same Name, Different IDs):")
    name_groups = df.groupby(['village_name', 'mandal'])
    for name_mandal, group in name_groups:
        unique_ids = group['village_id'].unique()
        if len(unique_ids) > 1:
            print(f"\nDifferent IDs for {name_mandal}: {unique_ids}")
            print(group[['village_id', 'source_file']])

    # 3. Check for "Inorder" - are IDs sequential?
    print("\nID Range Analysis:")
    for f in files:
        f_df = df[df['source_file'] == f]
        if f_df.empty: continue
        ids = f_df['village_id'].dropna().unique()
        if len(ids) > 0:
            print(f"{f}: Count={len(ids)}, Min={min(ids)}, Max={max(ids)}")
            # Check for gaps
            full_range = set(range(int(min(ids)), int(max(ids)) + 1))
            gaps = full_range - set(ids.astype(int))
            if gaps:
                print(f"  Gaps found: {len(gaps)} missing IDs in range.")
            else:
                print("  No gaps in range.")

if __name__ == "__main__":
    check_village_id_integrity()
