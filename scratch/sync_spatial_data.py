import geopandas as gpd
import pandas as pd
import os
import json

def build_master_geojson():
    data_dir = 'frontend/public/data'
    
    boundary_files = [
        'village_boundaries_imputed.geojson',
        'village_boundaries_ntr.geojson'
    ]
    
    all_boundaries = []
    for f in boundary_files:
        path = os.path.join(data_dir, f)
        if os.path.exists(path):
            print(f"Loading boundaries from {f}...")
            gdf = gpd.read_file(path)
            if gdf.crs is None: gdf.set_crs('EPSG:4326', inplace=True)
            # Ensure only basic columns to avoid pyogrio errors with complex types
            keep_cols = ['geometry', 'village_name', 'mandal', 'district', 'state']
            available = [c for c in keep_cols if c in gdf.columns]
            all_boundaries.append(gdf[available])
            
    base_gdf = pd.concat(all_boundaries, ignore_index=True)
    print(f"Total base boundaries gathered: {len(base_gdf)}")
    
    prediction_path = os.path.join(data_dir, 'map_data_predictions.geojson')
    print(f"Loading predictions from {prediction_path}...")
    pred_gdf = gpd.read_file(prediction_path)
    
    pred_data_cols = [
        'groundwater_level', 'predicted_groundwater_level', 
        'monthly_depths', 'monthly_depths_dates', 'groundwater_estimate',
        'risk_level', 'confidence', 'confidence_score', 'reliability'
    ]
    available_pred_cols = [c for c in pred_data_cols if c in pred_gdf.columns]
    
    # Create representative points
    pred_gdf['centroid'] = pred_gdf.geometry.representative_point()
    pred_points = pred_gdf.set_geometry('centroid')[available_pred_cols + ['centroid']]
    if pred_points.crs is None: pred_points.set_crs('EPSG:4326', inplace=True)
    
    print("Performing spatial join...")
    joined = gpd.sjoin(base_gdf, pred_points, how='left', predicate='contains')
    
    # Deduplicate by name/mandal
    joined = joined.drop_duplicates(subset=['village_name', 'mandal', 'district'])
    
    # Assign NEW sequential IDs 1-N
    joined = joined.sort_values(['district', 'mandal', 'village_name'])
    joined['village_id'] = range(1, len(joined) + 1)
    
    # Handle missing data
    if 'groundwater_level' in joined.columns:
        joined['groundwater_level'] = joined['groundwater_level'].fillna(joined.get('predicted_groundwater_level', 0))
    
    # Clean up any potential 'object' columns that cause JSON errors
    for col in joined.columns:
        if col == 'geometry': continue
        if joined[col].dtype == 'object':
             # Try to convert to string if not already
             joined[col] = joined[col].astype(str).replace('nan', '')

    print(f"Saving {len(joined)} villages...")
    
    output_path = os.path.join(data_dir, 'map_data_predictions.geojson')
    
    # Use to_json() which is more robust than to_file() for complex GeoJSONs
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(joined.to_json())
    
    # Sync others
    for other in ['villages.geojson', 'village_boundaries.geojson']:
        with open(os.path.join(data_dir, other), 'w', encoding='utf-8') as f:
            f.write(joined.to_json())
    
    print("Done!")

if __name__ == "__main__":
    build_master_geojson()
