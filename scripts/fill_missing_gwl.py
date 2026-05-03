import geopandas as gpd
import pandas as pd
import numpy as np
from sklearn.neighbors import KNeighborsRegressor
import os
import sys

def fill_missing_values(geojson_path):
    if not os.path.exists(geojson_path):
        print(f"File {geojson_path} not found.")
        return

    print(f"\nProcessing {geojson_path}...")
    try:
        gdf = gpd.read_file(geojson_path)
    except Exception as e:
        print(f"Error reading {geojson_path}: {e}")
        return
    
    # Identify villages with and without piezometer data
    # Based on our analysis, villages with obs_station_count > 0 have ground truth.
    # Villages with obs_station_count == 0 (760 villages) need interpolation.
    
    if 'obs_station_count' in gdf.columns:
        mask_missing = (gdf['obs_station_count'] == 0)
    else:
        # Fallback to looking for NaNs or 0s in groundwater_level
        target_cols = ['groundwater_level', 'gw_level', 'observed_gwl']
        found_col = next((c for c in target_cols if c in gdf.columns), None)
        if found_col:
            mask_missing = gdf[found_col].isna() | (gdf[found_col] == 0)
        else:
            print(f"Required columns not found in {geojson_path}.")
            return

    found_col = 'groundwater_level' if 'groundwater_level' in gdf.columns else 'gw_level'
    if found_col not in gdf.columns:
        print(f"No target level column found in {geojson_path}")
        return

    has_data = gdf[~mask_missing].copy()
    missing_data = gdf[mask_missing].copy()
    
    print(f"Total villages: {len(gdf)}")
    print(f"Villages with observed data: {len(has_data)}")
    print(f"Villages to interpolate: {len(missing_data)}")
    
    if len(has_data) == 0:
        print("No observed data found to interpolate from.")
        return

    if len(missing_data) == 0:
        print("No missing data to fill.")
        return

    # Spatial Interpolation using KNN
    print("Performing spatial interpolation (KNN)...")
    
    # Use centroids for coordinates
    has_data['x'] = has_data.geometry.centroid.x
    has_data['y'] = has_data.geometry.centroid.y
    missing_data['x'] = missing_data.geometry.centroid.x
    missing_data['y'] = missing_data.geometry.centroid.y

    X_train = has_data[['x', 'y']]
    y_train = has_data[found_col]
    X_pred = missing_data[['x', 'y']]
    
    # Try to add topography and rainfall if available
    extra_features = ['elevation', 'recharge_index', 'rainfall_proxy', 'distance_to_nearest_tank_km']
    used_extra = []
    for feat in extra_features:
        if feat in has_data.columns and has_data[feat].notna().all() and missing_data[feat].notna().all():
            if has_data[feat].nunique() > 1:
                used_extra.append(feat)
    
    if used_extra:
        X_train = has_data[['x', 'y'] + used_extra]
        X_pred = missing_data[['x', 'y'] + used_extra]
        print(f"Using extra features for interpolation: {used_extra}")

    # Train KNN Regressor
    n_neighbors = min(5, len(has_data))
    knn = KNeighborsRegressor(n_neighbors=n_neighbors, weights='distance')
    knn.fit(X_train, y_train)
    
    # Predict
    predictions = knn.predict(X_pred)
    
    # Update the GeoJSON
    gdf.loc[mask_missing, found_col] = predictions
    gdf['predicted_groundwater_level'] = gdf[found_col]
    
    # Add metadata flags
    gdf['data_source'] = 'Observed (Piezometer)'
    gdf.loc[mask_missing, 'data_source'] = 'Estimated'
    gdf.loc[mask_missing, 'is_estimated'] = True
    gdf.loc[~mask_missing, 'is_estimated'] = False
    
    # Update confidence
    if 'confidence' in gdf.columns:
        gdf.loc[mask_missing, 'confidence'] = 0.75
        gdf.loc[~mask_missing, 'confidence'] = 0.95
    
    print("Saving updated GeoJSON...")
    # Also ensure we save to the multiple locations mentioned in requirements
    gdf.to_file(geojson_path, driver='GeoJSON')
    print(f"Successfully updated {geojson_path}")

if __name__ == "__main__":
    paths = [
        'frontend/public/data/map_data_predictions.geojson',
        'output/map_data_predictions.geojson',
        'data/exports/map_data_predictions.geojson',
        'data/exports/map_data_predictions_ntr.geojson',
        'frontend/public/data/map_data_predictions_ntr.geojson'
    ]
    for p in paths:
        if os.path.exists(p):
            fill_missing_values(p)
        else:
            print(f"Path not found: {p}")


