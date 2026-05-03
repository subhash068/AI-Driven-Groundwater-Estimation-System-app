import pandas as pd
import geopandas as gpd
import os
import json

def normalize_name(s):
    if not s or pd.isna(s): return ""
    return str(s).strip().upper().replace(" ", "").replace(".", "")

def rebuild_all():
    data_dir = 'frontend/public/data'
    
    # 1. Load the tabular data
    print("Loading final_dataset.json...")
    df = pd.read_json(os.path.join(data_dir, 'final_dataset.json'))
    df.columns = [c.lower() for c in df.columns]
    
    # 2. Load all boundaries
    boundary_files = [
        'village_boundaries_imputed.geojson',
        'village_boundaries_ntr.geojson',
        'villages.geojson',
        'village_boundaries.geojson'
    ]
    
    all_boundaries = []
    for f in boundary_files:
        path = os.path.join(data_dir, f)
        if os.path.exists(path):
            print(f"Loading boundaries from {f}...")
            try:
                gdf = gpd.read_file(path)
                if gdf.crs is None: gdf.set_crs('EPSG:4326', inplace=True)
                gdf.columns = [c.lower() for c in gdf.columns]
                keep = ['geometry', 'village_name', 'mandal', 'district', 'state']
                available = [c for c in keep if c in gdf.columns]
                all_boundaries.append(gdf[available])
            except: pass
                
    base_gdf = pd.concat(all_boundaries, ignore_index=True)
    base_gdf = base_gdf.drop_duplicates(subset=['village_name', 'mandal', 'district'])
    print(f"Total unique boundaries: {len(base_gdf)}")

    # 3. Create fuzzy keys for matching
    # Primary Key: District + Mandal + Village
    df['key_full'] = df.apply(lambda r: (normalize_name(r.get('district','')), normalize_name(r.get('mandal','')), normalize_name(r.get('village_name',''))), axis=1)
    base_gdf['key_full'] = base_gdf.apply(lambda r: (normalize_name(r.get('district','')), normalize_name(r.get('mandal','')), normalize_name(r.get('village_name',''))), axis=1)
    
    # Secondary Key: District + Village (ignoring Mandal)
    df['key_dv'] = df.apply(lambda r: (normalize_name(r.get('district','')), normalize_name(r.get('village_name',''))), axis=1)
    base_gdf['key_dv'] = base_gdf.apply(lambda r: (normalize_name(r.get('district','')), normalize_name(r.get('village_name',''))), axis=1)

    # 4. Perform the merge
    print("Performing primary merge (District+Mandal+Village)...")
    merged_full = base_gdf.merge(df.drop(columns=['village_name', 'mandal', 'district', 'state'], errors='ignore'), on='key_full', how='inner')
    
    matched_full_keys = set(merged_full['key_full'])
    df_remaining = df[~df['key_full'].isin(matched_full_keys)]
    base_remaining = base_gdf[~base_gdf['key_full'].isin(matched_full_keys)]
    
    print(f"  Primary merge matched {len(merged_full)} villages.")
    print(f"  Attempting secondary merge (District+Village) for {len(df_remaining)} orphans...")
    
    # Secondary merge
    merged_dv = base_remaining.merge(df_remaining.drop(columns=['village_name', 'mandal', 'district', 'state', 'key_full'], errors='ignore'), on='key_dv', how='inner')
    print(f"  Secondary merge matched {len(merged_dv)} more villages.")
    
    final_gdf = pd.concat([merged_full, merged_dv], ignore_index=True)
    print(f"Total matched villages: {len(final_gdf)}")

    # 5. Clean up and assign clean IDs
    final_gdf = final_gdf.sort_values(['district', 'mandal', 'village_name'])
    final_gdf['village_id'] = range(1, len(final_gdf) + 1)
    
    if 'groundwater_level' not in final_gdf.columns and 'gw_level' in final_gdf.columns:
        final_gdf['groundwater_level'] = final_gdf['gw_level']
    
    # 6. Save
    output_path = os.path.join(data_dir, 'map_data_predictions.geojson')
    print(f"Saving {len(final_gdf)} villages to {output_path}...")
    
    for col in final_gdf.columns:
        if col == 'geometry': continue
        if final_gdf[col].dtype == 'object':
            final_gdf[col] = final_gdf[col].apply(lambda x: json.dumps(x) if isinstance(x, (list, dict)) else str(x) if pd.notna(x) else "")
            
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_gdf.to_json())
        
    final_gdf.to_file(os.path.join(data_dir, 'villages.geojson'), driver='GeoJSON')
    print("Restore complete!")

if __name__ == "__main__":
    rebuild_all()
