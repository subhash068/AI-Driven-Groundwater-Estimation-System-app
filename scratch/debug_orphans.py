import pandas as pd
import geopandas as gpd
import os

def normalize_name(s):
    if not s or pd.isna(s): return ""
    return str(s).strip().upper().replace(" ", "").replace(".", "")

def debug_orphans():
    data_dir = 'frontend/public/data'
    df = pd.read_json(os.path.join(data_dir, 'final_dataset.json'))
    df.columns = [c.lower() for c in df.columns]
    
    boundary_files = ['village_boundaries_imputed.geojson', 'village_boundaries_ntr.geojson']
    all_boundaries = []
    for f in boundary_files:
        path = os.path.join(data_dir, f)
        if os.path.exists(path):
            gdf = gpd.read_file(path)
            gdf.columns = [c.lower() for c in gdf.columns]
            all_boundaries.append(gdf)
    base_gdf = pd.concat(all_boundaries, ignore_index=True)
    
    df['key_full'] = df.apply(lambda r: (normalize_name(r.get('district','')), normalize_name(r.get('mandal','')), normalize_name(r.get('village_name',''))), axis=1)
    base_gdf['key_full'] = base_gdf.apply(lambda r: (normalize_name(r.get('district','')), normalize_name(r.get('mandal','')), normalize_name(r.get('village_name',''))), axis=1)
    
    matched_keys = set(base_gdf['key_full'])
    orphans = df[~df['key_full'].isin(matched_keys)]
    
    print(f"Orphans in DF: {len(orphans)}")
    print(orphans[['district', 'mandal', 'village_name']].head(20))
    
    print("\nSample boundaries that might match:")
    for _, row in orphans.head(5).iterrows():
        name = normalize_name(row['village_name'])[:4]
        matches = base_gdf[base_gdf['village_name'].str.upper().str.contains(name, na=False)]
        if not matches.empty:
            print(f"For orphan {row['village_name']} ({row['mandal']}), found boundaries:")
            print(matches[['district', 'mandal', 'village_name']])

if __name__ == "__main__":
    debug_orphans()
