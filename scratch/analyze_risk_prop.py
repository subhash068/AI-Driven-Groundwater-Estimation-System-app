import json
import os

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'

def analyze_risk_prop():
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
        
        # Follow logic in normalizeVillageProperties
        risk = str(props.get('risk_level') or props.get('normalized_risk') or "").strip().lower()
        
        # Mapping logic from normalizeVillageProperties
        if risk == "high": risk = "critical"
        if risk in ["medium", "moderate", "caution"]: risk = "warning"
        if risk == "low": risk = "safe"
        
        total += 1
        if risk == "critical":
            critical += 1
        elif risk == "warning":
            warning += 1
        else:
            safe += 1

    print(f"Total Villages: {total}")
    print(f"Safe: {safe}")
    print(f"Warning/Caution: {warning}")
    print(f"Critical: {critical}")

if __name__ == "__main__":
    analyze_risk_prop()
