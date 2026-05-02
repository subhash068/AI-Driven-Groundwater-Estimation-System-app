import os
from pathlib import Path
import shutil

LEGACY_SOURCE_DIR = Path(r"C:/Users/windows-11/Desktop/Document from A Momin")
TARGET_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
ENV_SOURCE_DIR = os.getenv("GROUNDWATER_SOURCE_DIR")
CONFIGURED_SOURCE_DIR = Path(ENV_SOURCE_DIR).expanduser() if ENV_SOURCE_DIR else None

FILE_NAMES = [
    "Aquifers_Krishna.zip",
    "K_Canals.zip",
    "K_DEM1.zip",
    "K_Drain.zip",
    "GM_Krishna.zip",
    "GTWells_Krishna.zip",
    "KrishnaLULC.zip",
    "K_Strms.zip",
    "K_Tanks.zip",
    "Pumping Data.xlsx",
    "PzWaterLevel_2024.xlsx",
    "Village_Mandal_DEM_Soils_MITanks_Krishna.zip",
    "Lulc legend.jpeg",
]


def _source_dirs() -> list[Path]:
    candidates: list[Path] = []
    if CONFIGURED_SOURCE_DIR is not None:
        candidates.append(CONFIGURED_SOURCE_DIR)
    candidates.append(LEGACY_SOURCE_DIR)
    return [path for path in candidates if path.exists()]


def _find_source_file(name: str) -> Path | None:
    for source_dir in _source_dirs():
        candidate = source_dir / name
        if candidate.exists():
            return candidate
    return None


def stage() -> list[Path]:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in FILE_NAMES:
        dst = TARGET_DIR / name
        src = _find_source_file(name)
        if dst.exists():
            if src is not None and src.resolve() != dst.resolve():
                try:
                    if src.stat().st_mtime > dst.stat().st_mtime:
                        shutil.copy2(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
            copied.append(dst)
            continue
        if src is None:
            continue
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        copied.append(dst)
    return copied


if __name__ == "__main__":
    files = stage()
    if not files:
        print("No files staged. Verify source path and filenames.")
    else:
        print("Staged files:")
        for path in files:
            print(f" - {path}")
