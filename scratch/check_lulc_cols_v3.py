import json
import ijson

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'

with open(path, 'r') as f:
    features = ijson.items(f, 'features.item')
    for feature in features:
        props = feature.get('properties', {})
        print("Keys:", list(props.keys()))
        lulc_cols = [k for k in props.keys() if 'pct' in k]
        print("LULC Columns:", lulc_cols)
        break
