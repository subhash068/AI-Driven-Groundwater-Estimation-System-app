import geopandas as gpd
path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'
gdf = gpd.read_file(path, rows=1)
lulc_cols = [c for c in gdf.columns if 'pct' in c]
print("LULC Columns:", lulc_cols)
