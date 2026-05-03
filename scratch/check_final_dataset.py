import json
import ijson

path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\frontend\public\data\final_dataset.json'

with open(path, 'r') as f:
    items = ijson.items(f, 'item')
    for item in items:
        print("Keys:", list(item.keys()))
        lulc_cols = [k for k in item.keys() if 'pct' in k]
        print("LULC Columns:", lulc_cols)
        break
