import json
import os

# Load imputed data
imputed_path = 'frontend/public/data/village_boundaries_imputed.geojson'
if not os.path.exists(imputed_path):
    print(f"Error: {imputed_path} not found")
    exit(1)

with open(imputed_path, 'r', encoding='utf-8') as f:
    imputed_data = json.load(f)

# Create a map of village_id to properties
imputed_map = {}
for feature in imputed_data['features']:
    props = feature['properties']
    v_id = props.get('village_id')
    if v_id is not None:
        imputed_map[int(v_id)] = props

# Load predictions data
pred_path = 'frontend/public/data/map_data_predictions.geojson'
if not os.path.exists(pred_path):
    print(f"Error: {pred_path} not found")
    exit(1)

with open(pred_path, 'r', encoding='utf-8') as f:
    pred_data = json.load(f)

updated_count = 0
fields_to_sync = [
    'recharge_index', 'recharge_score', 'recharge_potential',
    'elevation', 'monsoon_draft', 'extraction_stress',
    'wells_total', 'well_count',
    'groundwater_level', 'predicted_groundwater_level',
    'monthly_depths', 'monthly_depths_full', 'monthly_depths_dates',
    'monthly_depths_full_dates'
]

for feature in pred_data['features']:
    props = feature['properties']
    v_id = props.get('village_id')
    if v_id is not None and int(v_id) in imputed_map:
        imputed_props = imputed_map[int(v_id)]
        
        # Check if the village has '0.0' or missing data in pred
        is_missing = False
        if props.get('predicted_groundwater_level') == 0.0 or props.get('groundwater_level') == 0.0:
            is_missing = True
        if not props.get('monthly_depths') or props.get('monthly_depths') == "[]":
            is_missing = True
            
        if is_missing:
            # Sync fields from imputed if they exist there and are better
            for field in fields_to_sync:
                val = imputed_props.get(field)
                if val is not None and val != 0.0 and val != "[]":
                    props[field] = val
            
            # Also sync imputed specifically named fields
            if 'seasonal_variation' in imputed_props:
                props['seasonal_variation'] = imputed_props['seasonal_variation']
            
            # Ensure is_hydrated is true if we have data
            props['is_hydrated'] = True
            updated_count += 1

print(f"Updated {updated_count} villages in {pred_path} with data from {imputed_path}")

with open(pred_path, 'w', encoding='utf-8') as f:
    json.dump(pred_data, f)
