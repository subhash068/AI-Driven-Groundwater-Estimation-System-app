import json
import os

data_path = r'frontend/public/data/final_dataset.json'
if os.path.exists(data_path):
    with open(data_path, 'r') as f:
        data = json.load(f)
        depths = [d.get('gw_level') for d in data if d.get('gw_level') is not None]
        if depths:
            print(f"Total entries: {len(data)}")
            print(f"Count: {len(depths)}")
            print(f"Avg: {sum(depths)/len(depths):.2f}")
            print(f"Max: {max(depths):.2f}")
            print(f"Min: {min(depths):.2f}")
            print(f"Critical (>30): {len([d for d in depths if d >= 30])}")
            print(f"Caution (15-30): {len([d for d in depths if 15 <= d < 30])}")
            print(f"Safe (<15): {len([d for d in depths if d < 15])}")
        else:
            print("No depth data found.")
else:
    print(f"File {data_path} not found.")
