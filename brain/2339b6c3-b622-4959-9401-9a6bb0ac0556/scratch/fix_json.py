import json
import os

path = 'frontend/public/data/final_dataset.json'
if os.path.exists(path):
    print(f"Reading {path}...")
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    
    # Simple fix for common trailing comma before end of array
    if content.endswith(',]'):
        print("Found trailing comma at end of array. Fixing...")
        content = content[:-2] + ']'
    elif content.endswith(',\n]'):
        print("Found trailing comma at end of array (with newline). Fixing...")
        content = content[:-3] + '\n]'
    
    try:
        json.loads(content)
        print("JSON is now valid.")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    except json.JSONDecodeError as e:
        print(f"JSON is still invalid: {e}")
        # Try a more aggressive fix if it's just a trailing comma somewhere
        # But for 17MB, we should be careful.
else:
    print(f"File {path} not found.")
