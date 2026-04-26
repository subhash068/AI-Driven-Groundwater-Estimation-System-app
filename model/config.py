from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = REPO_ROOT / "data" / "processed"
DATA_EXPORTS_DIR = REPO_ROOT / "data" / "exports"
ARTIFACTS_DIR = REPO_ROOT / "model" / "artifacts"

LULC_CLASS_COLOR = {
    "Water": "#3b82f6",
    "Trees": "#22c55e",
    "Flooded Vegetation": "#86efac",
    "Crops": "#facc15",
    "Built Area": "#ef4444",
    "Bare Ground": "#d4d4d4",
    "Snow/Ice": "#e5e7eb",
    "Clouds": "#9ca3af",
    "Rangeland": "#fcd34d",
}

NOISE_CLASSES = {"Snow/Ice", "Clouds"}
ACTIVE_LULC_CLASSES = [
    "Water",
    "Trees",
    "Flooded Vegetation",
    "Crops",
    "Built Area",
    "Bare Ground",
    "Rangeland",
]

KRIGING_STRATEGIES = {"residual", "direct"}
DEFAULT_CRS = "EPSG:4326"
AREA_CRS = "EPSG:32644"
