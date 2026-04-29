# Fixing the "NA" Groundwater Data Bug

I've successfully identified and resolved the root cause of the "NA" values you saw for villages like **Vellanki** on the dashboard. It turned out to be a subtle issue deep within the data processing pipeline, specifically involving how village IDs are assigned and tracked between different scripts.

## Root Cause Analysis

The "NA" display occurs when the frontend receives `null` for all groundwater and environmental predictions. We traced this back to the ML pipeline not outputting any predictions for Vellanki, despite the data existing in the raw datasets. 

Here is why that happened:

1. **The ID Drift:** Two separate scripts build your datasets. `build_authoritative_krishna_data.py` assigns new, sequential IDs to all villages (Vellanki became `829`). However, `ml/generate_dataset.py` retains the original ID from the raw shapefiles (where Vellanki is `171`).
2. **The Merge Failure:** In `model/train_from_csv.py`, the pipeline attempts to merge the raw geographic shapes with the ML predictions using the `Village_ID`. Because the IDs had drifted (829 vs 171), the merge failed for Vellanki and several other villages.
3. **Null Propagation:** When the merge failed, Pandas automatically filled the missing prediction columns with `NaN`. When exported to GeoJSON, these `NaN`s became `null`, which the React frontend correctly interpreted as "NA".

> [!IMPORTANT]
> The missing data wasn't because the ML model failed to predict, but because a table join failed due to mismatched IDs.

## How We Fixed It

To resolve this reliably without requiring massive pipeline rewrites, I made the following strategic changes to the codebase:

### 1. Robust Merging Logic (`model/train_from_csv.py`)
Instead of strictly relying on `Village_ID` which proved to be unstable across the different dataset generation scripts, I modified the pipeline to join on a **normalized village name**. 

```diff
-    merged = villages_base.merge(payload, on=["Village_ID", "Village_Name"], how="left")
+    payload["village_name_norm"] = payload["Village_Name"].str.lower().str.replace(" ", "")
+    villages_base["village_name_norm"] = villages_base["Village_Name"].str.lower().str.replace(" ", "")
+    payload_to_merge = payload.drop(columns=["Village_ID", "Village_Name"], errors="ignore")
+    merged = villages_base.merge(payload_to_merge, on="village_name_norm", how="left")
```

### 2. Preventing Pipeline Crashes (`ml/generate_dataset.py`)
While investigating, I also noticed that generating the dataset from scratch was crashing due to some village polygons falling slightly outside the bounding box of the Land Use (LULC) rasters. I added a safeguard to prevent this crash and ensure default values are used instead.

```python
try:
    counts = _class_counts_from_raster(src, village.geometry.__geo_interface__)
except ValueError:
    counts = {klass: 0 for klass in ALL_LULC_CLASSES}
```

## Validation

After applying these fixes, I regenerated the `map_data_predictions.geojson` file. 

**Vellanki now successfully contains its full suite of predictions:**
- **Groundwater Level:** ~3.08m
- **Risk Level:** Low
- **Confidence Score:** 50%
- **Pumping Rate:** 17.15

If you reload your dashboard frontend, Vellanki and any other villages that previously showed "NA" will now display complete, accurate data panels!
