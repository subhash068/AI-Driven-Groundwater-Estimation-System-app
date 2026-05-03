import geopandas as gpd
import pandas as pd
import numpy as np
from sklearn.neighbors import KNeighborsRegressor
import os
import ast

def parse_series(val):
    if isinstance(val, (list, np.ndarray)):
        return val
    if isinstance(val, str):
        try:
            # Handle space-separated numbers if they are in a string like "[ 1.2 3.4 ]"
            s = val.strip()
            if s.startswith('[') and s.endswith(']'):
                s = s[1:-1].strip()
                return [float(x) for x in s.split()]
            return ast.literal_eval(val)
        except:
            return []
    return []

def is_valid(s):
    return len(s) > 0 and any(x is not None and not np.isnan(float(x)) for x in s)

def fill_missing_series():
    geojson_path = 'frontend/public/data/map_data_predictions.geojson'
    if not os.path.exists(geojson_path):
        return

    print(f"Loading {geojson_path}...")
    gdf = gpd.read_file(geojson_path)
    
    # Parse series
    for col in ['monthly_actual_gw', 'monthly_predicted_gw']:
        gdf[col] = gdf[col].apply(parse_series)

    # Use monthly_predicted_gw as the anchor because actual might be missing
    has_series = gdf[gdf['monthly_predicted_gw'].apply(is_valid)].copy()
    missing_series = gdf[~gdf['monthly_predicted_gw'].apply(is_valid)].copy()
    
    print(f"Villages with predicted series: {len(has_series)}")
    print(f"Villages missing predicted series: {len(missing_series)}")
    
    if len(has_series) == 0:
        print("No series data to interpolate.")
        return

    has_series['x'] = has_series.geometry.centroid.x
    has_series['y'] = has_series.geometry.centroid.y
    missing_series['x'] = missing_series.geometry.centroid.x
    missing_series['y'] = missing_series.geometry.centroid.y
    
    X_train = has_series[['x', 'y']]
    X_pred = missing_series[['x', 'y']]
    
    for col in ['monthly_actual_gw', 'monthly_predicted_gw']:
        print(f"Interpolating {col}...")
        all_series = has_series[col].tolist()
        if not all_series: continue
        
        max_len = max(len(s) for s in all_series)
        matrix = np.full((len(has_series), max_len), np.nan)
        for i, s in enumerate(all_series):
            for j, val in enumerate(s[:max_len]):
                if val is not None:
                    try:
                        matrix[i, j] = float(val)
                    except:
                        pass
            
        pred_matrix = np.zeros((len(missing_series), max_len))
        for m in range(max_len):
            y_month = matrix[:, m]
            valid_mask = ~np.isnan(y_month)
            if valid_mask.sum() > 0:
                mean_val = np.nanmean(y_month)
                if valid_mask.sum() >= 1:
                    knn = KNeighborsRegressor(n_neighbors=min(5, valid_mask.sum()), weights='distance')
                    knn.fit(X_train[valid_mask], y_month[valid_mask])
                    pred_matrix[:, m] = knn.predict(X_pred)
                else:
                    pred_matrix[:, m] = mean_val
            else:
                pred_matrix[:, m] = 0.0 # Fallback
                
        # Fill missing values back into GDF
        new_series = [list(row) for row in pred_matrix]
        gdf.loc[missing_series.index, col] = pd.Series(new_series, index=missing_series.index)

    print("Saving updated GeoJSON...")
    gdf.to_file(geojson_path, driver='GeoJSON')
    print("Success.")

if __name__ == "__main__":
    fill_missing_series()
