import json

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\map_data_predictions.geojson'
with open(path, 'r') as f:
    # Read a chunk to find the first feature
    data = f.read(100000)
    
# Find the start of the first feature
start = data.find('{"type":"Feature"')
if start != -1:
    end = data.find('}', data.find('"properties":')) + 1
    # This is a bit hacky, let's just find the first 'properties' and closing brace
    prop_start = data.find('"properties":')
    if prop_start != -1:
        # Find closing brace of properties
        brace_count = 0
        for i in range(prop_start + len('"properties":'), len(data)):
            if data[i] == '{': brace_count += 1
            if data[i] == '}':
                if brace_count == 0:
                    prop_json = data[prop_start + len('"properties":') : i+1]
                    props = json.loads(prop_json)
                    print("Keys:", list(props.keys()))
                    lulc_cols = [k for k in props.keys() if 'pct' in k]
                    print("LULC Columns:", lulc_cols)
                    break
                else:
                    brace_count -= 1
