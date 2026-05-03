import geopandas as gpd
import json

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'
gdf = gpd.read_file(path, rows=5)
print("Columns:", gdf.columns.tolist())
print("Sample properties:", gdf.iloc[0].to_dict())
