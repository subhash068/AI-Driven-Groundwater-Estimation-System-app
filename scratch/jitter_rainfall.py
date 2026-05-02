
import json
import numpy as np

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'

with open(path, 'r') as f:
    data = json.load(f)

for feature in data['features']:
    props = feature['properties']
    village_id = props.get('village_id', 0)
    
    # Process monthly_rainfall
    rainfall_raw = props.get('monthly_rainfall')
    if isinstance(rainfall_raw, str):
        try:
            rainfall = json.loads(rainfall_raw)
        except:
            rainfall = None
    elif isinstance(rainfall_raw, list):
        rainfall = rainfall_raw
    else:
        rainfall = None
        
    if rainfall:
        # Add deterministic jitter based on village_id
        jitter = ((village_id * 137) % 31 - 15) / 100.0
        new_rainfall = [round(r * (1.0 + jitter), 2) if r is not None else None for r in rainfall]
        
        # Write back
        if isinstance(rainfall_raw, str):
            props['monthly_rainfall'] = json.dumps(new_rainfall)
        else:
            props['monthly_rainfall'] = new_rainfall

with open(path, 'w') as f:
    json.dump(data, f)

print("Successfully updated rainfall data with jitter for all villages.")
