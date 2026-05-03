import geopandas as gpd

def fix_geojson_districts():
    path = 'frontend/public/data/villages.geojson'
    gdf = gpd.read_file(path)
    gdf.columns = [c.lower() for c in gdf.columns]
    
    ntr_patterns = [
        'AKONDURU', 'CHANDARLAPADU', 'GKONDURU', 'GAMPALAGUDEM', 
        'JAGGAYYAPETA', 'KANCHIKACHERLA', 'IBRAHIMPATNAM', 'TIRUVURU', 
        'MYLAVARAM', 'NANDIGAMA', 'PENUGANCHIPROLU', 'VISSANNAPETA', 
        'VATSAVAI', 'VEERULLAPADU', 'VIJAYAWADA', 'REDDIGUDEM'
    ]
    
    def is_ntr(mandal):
        m = str(mandal).upper().replace(' ', '').replace('.', '')
        return any(p in m for p in ntr_patterns)

    gdf.loc[gdf['mandal'].apply(is_ntr), 'district'] = 'NTR'
    
    gdf.to_file(path, driver='GeoJSON')
    print("GeoJSON District Counts:")
    print(gdf['district'].value_counts())

if __name__ == "__main__":
    fix_geojson_districts()
