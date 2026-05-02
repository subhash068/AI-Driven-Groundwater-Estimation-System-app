import json

# Load base village boundaries to get district/mandal mapping
with open('frontend/public/data/village_boundaries_imputed.geojson', 'r', encoding='utf-8') as f:
    base_data = json.load(f)

id_to_meta = {}
for f in base_data['features']:
    props = f['properties']
    v_id = props.get('village_id')
    if v_id is not None:
        id_to_meta[int(v_id)] = {
            'district': props.get('district'),
            'mandal': props.get('mandal'),
            'village_name': props.get('village_name')
        }

# Load predictions GeoJSON
pred_path = 'frontend/public/data/map_data_predictions.geojson'
with open(pred_path, 'r', encoding='utf-8') as f:
    pred_data = json.load(f)

count = 0
for f in pred_data['features']:
    props = f['properties']
    v_id = props.get('village_id')
    if v_id is not None and int(v_id) in id_to_meta:
        meta = id_to_meta[int(v_id)]
        props['district'] = meta['district']
        props['mandal'] = meta['mandal']
        # props['village_name'] = meta['village_name'] # Already there but ensure consistency
        count += 1

print(f"Updated {count} features with district and mandal information.")

with open(pred_path, 'w', encoding='utf-8') as f:
    json.dump(pred_data, f)
