import json

path = 'frontend/public/data/final_dataset.json'
try:
    with open(path, 'r', encoding='utf-8') as f:
        json.load(f)
    print("JSON is valid.")
except json.JSONDecodeError as e:
    print(f"JSON is invalid: {e}")
    print(f"Error at char {e.pos}")
    with open(path, 'r', encoding='utf-8') as f:
        f.seek(max(0, e.pos - 50))
        context = f.read(100)
        print(f"Context: ...{context}...")
