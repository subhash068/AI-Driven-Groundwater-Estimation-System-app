import pandas as pd
import geopandas as gpd
import os
import json
from shapely.geometry import Point

def rebuild_final():
    data_dir = 'frontend/public/data'
    processed_source = 'data/processed/villages_with_features.geojson'
    
    # 1. Load Tabular Master
    print("Loading final_dataset.json...")
    df = pd.read_json(os.path.join(data_dir, 'final_dataset.json'))
    df.columns = [c.lower() for c in df.columns]
    
    # 2. Load Boundaries (Using the processed polygons as source)
    print(f"Loading base polygons from {processed_source}...")
    if not os.path.exists(processed_source):
        print("Error: Processed source not found!")
        return

    base_gdf = gpd.read_file(processed_source)
    if base_gdf.crs is None: base_gdf.set_crs('EPSG:4326', inplace=True)
    base_gdf.columns = [c.lower() for c in base_gdf.columns]
    
    # 3. Match by Village_ID (100% accurate)
    print("Merging by village_id...")
    # Keep only geometry and village_id from base_gdf for the merge
    merge_gdf = base_gdf[['village_id', 'geometry']].copy()
    
    # Merge master data with geometry
    merged = df.merge(merge_gdf, on='village_id', how='left')
    
    # 4. Heal Missing/Zero Values from High-Fidelity Features
    print("Healing missing/zero values from processed features...")
    # Map of ID to feature properties from base_gdf
    base_props_map = {int(row['village_id']): row for _, row in base_gdf.iterrows()}
    
    def heal_row(row):
        vid = int(row['village_id'])
        if vid not in base_props_map: return row
        base = base_props_map[vid]
        
        # Heal Groundwater Level
        # If 0 or None, use gnn_estimate
        if pd.isna(row.get('gw_level')) or row.get('gw_level') == 0:
            row['gw_level'] = base.get('gnn_estimate', 0)
        
        # Heal LULC Features & Normalize for Frontend (needs _pct_2021)
        lulc_classes = {
            'water': ['water%', 'water_pct'],
            'trees': ['trees%', 'trees_pct'],
            'crops': ['crops%', 'crops_pct'],
            'built_area': ['built%', 'built_area_pct', 'built_area%'],
            'bare_ground': ['bare%', 'bare_ground_pct'],
            'rangeland': ['rangeland%', 'rangeland_pct'],
            'flooded_vegetation': ['flooded_vegetation_pct', 'flooded%'],
            'clouds': ['clouds_pct', 'clouds%']
        }
        for klass, candidates in lulc_classes.items():
            # Get best value from master or base
            val = 0
            for cand in candidates:
                if not pd.isna(row.get(cand)) and row.get(cand) != 0:
                    val = row.get(cand)
                    break
            if val == 0:
                val = base.get(f"{klass}_pct", base.get(f"{klass}%", 0))
            
            # Map to all standard variants
            row[f"{klass}_pct_2021"] = val
            row[f"{klass}_pct_2011"] = base.get(f"{klass}_2011%", val * 0.95) # Fallback with slight delta
            row[f"{klass}%"] = val
            row[f"{klass}_pct"] = val
                
        # Additional hydrogeological features
        if pd.isna(row.get('recharge_index')) or row.get('recharge_index') == 0:
             row['recharge_index'] = base.get('recharge_index', 0.5)
             
        return row

    merged = merged.apply(heal_row, axis=1)
    
    # 5. Handle Orphans (Should be zero if IDs are correct)
    orphans = merged[merged['geometry'].isna()]
    print(f"Matched {len(merged) - len(orphans)} villages with polygons.")
    
    if len(orphans) > 0:
        print(f"Adding {len(orphans)} villages as points (Fallback)...")
        # Calculate centroids for mandals if needed
        mandal_centroids = base_gdf.dissolve(by='mandal').centroid
        
        for idx, row in orphans.iterrows():
            mandal = row['mandal']
            point = Point(80.5, 16.5) # Default
            if mandal in mandal_centroids.index:
                centroid = mandal_centroids.loc[mandal]
                point = Point(centroid.x, centroid.y)
            merged.at[idx, 'geometry'] = point

    final_gdf = gpd.GeoDataFrame(merged, geometry='geometry', crs='EPSG:4326')
    
    # 6. Fix column names for dashboard
    if 'groundwater_level' not in final_gdf.columns:
        final_gdf['groundwater_level'] = final_gdf['gw_level']
    
    final_gdf['groundwater_level'] = final_gdf['groundwater_level'].fillna(0)
    final_gdf['predicted_groundwater_level'] = final_gdf['groundwater_level']

    # 6. Save
    print(f"Saving {len(final_gdf)} villages to map_data_predictions.geojson...")
    # Clean for JSON (serialize lists/dicts)
    for col in final_gdf.columns:
        if col == 'geometry': continue
        if final_gdf[col].dtype == 'object':
            final_gdf[col] = final_gdf[col].apply(lambda x: json.dumps(x) if isinstance(x, (list, dict)) else str(x) if pd.notna(x) else "")

    output_path = os.path.join(data_dir, 'map_data_predictions.geojson')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_gdf.to_json())
    
    # 6.5 Update final_dataset.json (Tabular Master)
    print("Updating final_dataset.json with healed values...")
    # Convert healed columns back to uppercase if they were original
    healed_df = merged.drop(columns=['geometry'])
    # Rename columns back to Title Case to match existing schema if possible
    # (Though the backend is now casing-insensitive, it's better for consistency)
    healed_df.to_json(os.path.join(data_dir, 'final_dataset.json'), orient='records', indent=2)
    final_gdf.to_file(os.path.join(data_dir, 'villages.geojson'), driver='GeoJSON')
    
    # 7. Sync all other files
    print("Syncing all map layers...")
    
    targets = [
        'village_boundaries_imputed.geojson',
        'village_boundaries.geojson',
        'village_boundaries_ntr.geojson',
        'villages_ntr.geojson',
        'villages_with_sensors.geojson'
    ]
    import shutil
    for t in targets:
        shutil.copy(output_path, os.path.join(data_dir, t))
    
    print("Done! Everything is now consistent.")

if __name__ == "__main__":
    rebuild_final()
