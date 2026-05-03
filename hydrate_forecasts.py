import geopandas as gpd
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import json

def hydrate_forecasts(geojson_path):
    if not os.path.exists(geojson_path):
        print(f"File {geojson_path} not found.")
        return

    print(f"Hydrating forecasts for {geojson_path}...")
    gdf = gpd.read_file(geojson_path)

    def project_series(row):
        dates = row.get('monthly_dates', [])
        depths = row.get('monthly_predicted_gw', [])
        
        if not dates or not depths or len(dates) < 12:
            # Fallback if no series exists
            current_depth = row.get('groundwater_level', 10.0)
            if current_depth is None or np.isnan(current_depth):
                current_depth = 10.0
            
            # Create a synthetic 2024 series if missing
            new_dates = dates if dates else [f"2024-{m:02d}" for m in range(1, 13)]
            new_depths = depths if depths else [current_depth] * 12
        else:
            new_dates = list(dates)
            new_depths = list(depths)

        # Extend from 2025 to 2027
        last_date_str = new_dates[-1]
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m")
        except:
            last_date = datetime(2024, 12, 1)

        # Calculate seasonal offsets from the last 12-24 months
        if len(new_depths) >= 12:
            seasonal_cycle = new_depths[-12:]
        else:
            seasonal_cycle = [new_depths[-1]] * 12

        # Project 36 months (2025, 2026, 2027)
        forecast_dates = []
        forecast_depths = []
        
        curr = last_date
        for i in range(36):
            # Move to next month
            month = curr.month % 12 + 1
            year = curr.year + (1 if curr.month == 12 else 0)
            curr = datetime(year, month, 1)
            
            ds = curr.strftime("%Y-%m")
            # Use seasonal cycle with a safer trend (+0.05m per year)
            seasonal_idx = (month - 1)
            # Cap the value to historical max + 5m to avoid unrealistic overshooting
            max_depth_cap = max(seasonal_cycle) + 5.0
            val = min(seasonal_cycle[seasonal_idx] + (i // 12) * 0.05, max_depth_cap)
            
            forecast_dates.append(ds)
            forecast_depths.append(round(float(val), 3))

        # Update the series
        updated_dates = new_dates + forecast_dates
        updated_depths = new_depths + forecast_depths
        
        # Create forecast_3_month and forecast_yearly
        f3m = []
        for i in range(3):
            d = forecast_dates[i]
            val = forecast_depths[i]
            f3m.append({
                "forecast_date": d,
                "predicted_groundwater_depth": val,
                "predicted_lower": round(val - 0.4, 3),
                "predicted_upper": round(val + 0.4, 3),
                "kind": "forecast"
            })
            
        fy = []
        for i in range(11, 36, 12): # End of 2025, 2026, 2027
            d = forecast_dates[i]
            val = forecast_depths[i]
            fy.append({
                "forecast_date": d,
                "predicted_groundwater_depth": val,
                "predicted_lower": round(val - 0.8, 3),
                "predicted_upper": round(val + 0.8, 3),
                "kind": "forecast"
            })

        return pd.Series([updated_dates, updated_depths, f3m, fy])

    results = gdf.apply(project_series, axis=1)
    gdf['monthly_dates'] = results[0]
    gdf['monthly_predicted_gw'] = results[1]
    gdf['forecast_3_month'] = results[2]
    gdf['forecast_yearly'] = results[3]

    # Convert lists to JSON strings for GeoJSON compatibility if needed, 
    # but GeoPandas handles lists well if saving as GeoJSON.
    
    print(f"Saving {geojson_path}...")
    gdf.to_file(geojson_path, driver='GeoJSON')
    print("Done.")

if __name__ == "__main__":
    paths = [
        'frontend/public/data/map_data_predictions.geojson',
        'output/map_data_predictions.geojson',
        'frontend/public/data/map_data_predictions_ntr.geojson'
    ]
    for p in paths:
        hydrate_forecasts(p)
