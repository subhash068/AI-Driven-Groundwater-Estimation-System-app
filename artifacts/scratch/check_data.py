import zipfile
import geopandas as gpd
import os

paths = [
    'data/raw/Village_Mandal_DEM_Soils_MITanks_Krishna.zip',
    'data/raw/GTWells_Krishna.zip',
    'data/raw/Aquifers_Krishna.zip',
    'data/raw/GM_Krishna.zip'
]

for p in paths:
    if not os.path.exists(p):
        print(f"File not found: {p}")
        continue
    with zipfile.ZipFile(p) as zf:
        shps = [n for n in zf.namelist() if n.lower().endswith('.shp')]
        print(f"{p}: {shps}")
        if shps:
            try:
                gdf = gpd.read_file(f"zip://{p}!{shps[0]}")
                print(f"  Count: {len(gdf)}")
                print(f"  Columns: {list(gdf.columns)}")
            except Exception as e:
                print(f"  Error reading: {e}")
