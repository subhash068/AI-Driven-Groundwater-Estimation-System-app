import json

with open('frontend/public/data/map_data_predictions.geojson', 'r') as f:
    data = json.load(f)
    for feature in data['features']:
        if feature['properties'].get('village_name') == 'Ananthasagaram':
            print(json.dumps(feature['properties'], indent=2))
