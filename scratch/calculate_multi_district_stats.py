import geopandas as gpd
import pandas as pd
import numpy as np
import json

def calculate_metrics():
    gdf = gpd.read_file('frontend/public/data/map_data_predictions.geojson')
    
    # Standardize district names
    gdf['district'] = gdf['district'].fillna('Unknown').str.upper()
    
    districts = ['KRISHNA', 'NTR']
    results = {}
    
    for dist in districts:
        df = gdf[gdf['district'] == dist].copy()
        
        village_count = len(df)
        
        # Avg GWL
        avg_gwl = df['predicted_groundwater_level'].mean()
        
        # High Risk Count (Case Insensitive)
        high_risk = len(df[df['risk_level'].str.lower() == 'critical'])
        
        # Trend Analysis from monthly_predicted_gw
        slopes = []
        for _, row in df.iterrows():
            series = row.get('monthly_predicted_gw', [])
            
            # Geopandas might already have it as an array
            if isinstance(series, str):
                try:
                    series = json.loads(series)
                except:
                    series = []
            
            # If it's a numpy array, convert to list
            if hasattr(series, 'tolist'):
                series = series.tolist()
                
            if series and len(series) >= 2:
                # Calculate slope from last 6 months
                recent = series[-6:]
                if len(recent) >= 2:
                    slope = (recent[-1] - recent[0]) / (len(recent) - 1)
                    slopes.append(slope)
        
        avg_slope = np.mean(slopes) if slopes else 0.0
        
        # Trend Label
        if avg_slope > 0.02:
            trend_label = "Declining" # Depth increasing = water level dropping
        elif avg_slope < -0.02:
            trend_label = "Improving"
        else:
            trend_label = "Stable"
            
        results[dist] = {
            "Villages": village_count,
            "Avg GWL": f"{avg_gwl:.2f} m",
            "Avg Trend Slope": f"{avg_slope:+.3f} m/mo",
            "High-risk villages": high_risk,
            "Trend": trend_label
        }
    
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    calculate_metrics()
