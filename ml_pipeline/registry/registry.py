import json
from pathlib import Path
from datetime import datetime

class ModelRegistry:
    def __init__(self, registry_path: str = "output/models/registry.json"):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_registry()

    def _load_registry(self):
        if self.registry_path.exists():
            with open(self.registry_path, "r") as f:
                self.registry = json.load(f)
        else:
            self.registry = {"models": []}

    def _save_registry(self):
        with open(self.registry_path, "w") as f:
            json.dump(self.registry, f, indent=2)

    def register_model(self, model_name: str, version: str, metrics: dict, artifacts: dict):
        entry = {
            "model_name": model_name,
            "version": version,
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": metrics,
            "artifacts": artifacts
        }
        self.registry["models"].append(entry)
        self._save_registry()
        return entry

    def get_latest_model(self, model_name: str):
        models = [m for m in self.registry["models"] if m["model_name"] == model_name]
        if not models:
            return None
        return sorted(models, key=lambda x: x["timestamp"], reverse=True)[0]
