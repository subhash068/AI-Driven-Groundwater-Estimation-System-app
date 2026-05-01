from pathlib import Path
import shutil

SOURCE_DIR = Path(r"C:/Users/windows-11/Desktop/Document from A Momin")
TARGET_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

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


def stage() -> list[Path]:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in FILE_NAMES:
        src = SOURCE_DIR / name
        if not src.exists():
            continue
        dst = TARGET_DIR / name
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
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
