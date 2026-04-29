# Implementation Plan: Resolving Duplicate Villages & Conflicting Data

## Goal
Resolve the issue shown in the screenshot where the dashboard displays duplicate map popups and conflicting data panels for the same village (e.g., Vellanki).

## Root Cause Analysis
Based on the screenshot and codebase analysis, here is exactly what is happening:

1. **Overlapping Datasets:** The system loads data for the undivided **Krishna** district AND the newly formed **NTR** district. Since NTR was carved out of Krishna, villages like Vellanki exist in *both* datasets.
2. **Duplicate Rendering:** The frontend uses a location key consisting of `[District, Mandal, Village]`. Because the district names differ (`NTR` vs `KRISHNA`), the frontend treats them as two completely separate villages and renders two polygons stacked on top of each other.
3. **Conflicting Data Panels:** 
   - The **Krishna dataset** contains rich LULC (Crop/Soil) and functioning well counts, but its groundwater estimate is purely ML-based.
   - The **NTR dataset** was generated directly from piezometer Excel data, so it has actual piezometer depth measurements (3.04m) but lacks Soil/Crop types and total well counts.
   - When you click on the map, the UI panels randomly pull data from whichever overlapping polygon is clicked, causing the mismatch seen in the screenshot (e.g., "Total Wells: 0" but "Functioning Pump Wells: 70").

## Proposed Changes

We will fix this by deduplicating the villages in the frontend when the map loads, perfectly merging the rich data from both datasets.

### `frontend/src/services/api.js`
Modify the `reconcileMapFeatureCollections` function to merge overlapping villages from the Krishna and NTR datasets.
- Introduce a deduplication key based strictly on `[Mandal, Village]` (ignoring the shifting district boundary).
- When a village exists in both datasets, we will combine the rich Soil/Crop/LULC data from the Krishna dataset with the accurate piezometer readings and groundwater estimates from the NTR dataset.
- This will ensure only **one** clean polygon is rendered on the map, and the side panels will show a complete, unified view of all available data.

## User Review Required
> [!IMPORTANT]
> The deduplication will prioritize the newer **NTR** district label and its actual piezometer readings, while backfilling missing fields (like Soil Type and Well Counts) from the **Krishna** dataset. 

Please approve this plan to proceed with the frontend deduplication fix.
