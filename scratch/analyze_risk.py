import json
import os

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'

def analyze_risk():
    if not os.path.exists(path):
        print(f"Error: {path} not found")
        return

    with open(path, 'r') as f:
        data = json.load(f)

    features = data.get('features', [])
    safe = 0
    warning = 0
    critical = 0
    total = 0
    
    for f in features:
        props = f.get('properties', {})
        # Follow the logic in MapView.jsx for depth extraction
        depth_val = props.get('groundwater_estimate') or \
                    props.get('predicted_groundwater_level') or \
                    props.get('depth') or 0
        
        try:
            depth = float(depth_val)
        except (ValueError, TypeError):
            depth = 0
            
        total += 1
        # Logic from normalizeRiskLevel in MapView.jsx
        if depth >= 30:
            critical += 1
        elif depth >= 20:
            warning += 1
        else:
            safe += 1

    print(f"Total Villages: {total}")
    print(f"Safe (<20m): {safe}")
    print(f"Warning (20-30m): {warning}")
    print(f"Critical (>30m): {critical}")

if __name__ == "__main__":
    analyze_risk()
