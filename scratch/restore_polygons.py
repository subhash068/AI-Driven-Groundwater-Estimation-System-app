import geopandas as gpd

def restore_polygons():
    source_path = 'data/processed/villages_with_features.geojson'
    dest_path = 'frontend/public/data/villages.geojson'
    
    print(f"Loading polygons from {source_path}...")
    gdf = gpd.read_file(source_path)
    gdf.columns = [c.lower() for c in gdf.columns]
    
    ntr_patterns = [
        'AKONDURU', 'CHANDARLAPADU', 'GKONDURU', 'GAMPALAGUDEM', 
        'JAGGAYYAPETA', 'KANCHIKACHERLA', 'IBRAHIMPATNAM', 'TIRUVURU', 
        'MYLAVARAM', 'NANDigama', 'PENUGANCHIPROLU', 'VISSANNAPETA', 
        'VATSAVAI', 'VEERULLAPADU', 'VIJAYAWADA', 'REDDIGUDEM'
    ]
    
    def is_ntr(mandal):
        m = str(mandal).upper().replace(' ', '').replace('.', '')
        return any(p in m for p in ntr_patterns)

    # Apply NTR labels
    gdf.loc[gdf['mandal'].apply(is_ntr), 'district'] = 'NTR'
    
    # Filter for only Krishna and NTR (exclude Guntur/West Godavari if they are there)
    gdf = gdf[gdf['district'].isin(['KRISHNA', 'NTR'])]
    
    print(f"Saving {len(gdf)} villages to {dest_path}...")
    print(gdf['district'].value_counts())
    
    gdf.to_file(dest_path, driver='GeoJSON')
    print("Done!")

if __name__ == "__main__":
    restore_polygons()
