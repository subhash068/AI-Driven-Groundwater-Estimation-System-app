import pandas as pd
import numpy as np
import os
import json
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Point
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt
import seaborn as sns

# Set aesthetics
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (12, 8)

class GroundwaterEstimationSystem:
    def __init__(self, raw_data_dir: str, output_dir: str):
        self.raw_dir = Path(raw_data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.pz_path = self.raw_dir / "PzWaterLevel_2024.xlsx"
        self.pumping_path = self.raw_dir / "Pumping Data.xlsx"
        self.villages_zip = self.raw_dir / "Village_Mandal_DEM_Soils_MITanks_Krishna.zip"
        
        self.df_pz = None
        self.df_pumping = None
        self.gdf_villages = None
        self.df_features = None
        self.models = {}
        self.metrics = {}
        self.predictions = None

    # --- STEP 1: DATA UNDERSTANDING ---
    def load_data(self):
        print("Step 1: Loading Data...")
        # Load Piezometer Data
        self.df_pz = pd.read_excel(self.pz_path)
        
        # Load Pumping Data
        self.df_pumping = pd.read_excel(self.pumping_path, skiprows=1) # Skip header row
        self.df_pumping.columns = ['District', 'Mandal', 'Village', 'Structure_Type', 'Functioning_Wells', 'Draft_Monsoon', 'Draft_NonMonsoon']
        
        # Load Village Geometries (Shapefile inside ZIP)
        print("Loading village shapefiles...")
        self.gdf_villages = gpd.read_file(self.villages_zip, layer='OKri_Vil')
        
        # Standardize Village Names for merging
        # The layer OKri_Vil might have different column names than expected.
        # Let's find the correct name column.
        name_cols = [c for c in self.gdf_villages.columns if 'name' in c.lower() or 'vil' in c.lower()]
        if not name_cols:
            raise ValueError(f"Could not find village name column in {self.gdf_villages.columns}")
        
        self.village_name_col = 'DVNAME' if 'DVNAME' in self.gdf_villages.columns else name_cols[0]
        self.mandal_name_col = 'DMNAME' if 'DMNAME' in self.gdf_villages.columns else 'Mandal_Nam'
        
        self.gdf_villages['village_key'] = self.gdf_villages[self.village_name_col].astype(str).str.lower().str.strip()
        self.df_pumping['village_key'] = self.df_pumping['Village'].astype(str).str.lower().str.strip()
        
        # Also load soil type from OKri_Soils if possible to enrich data
        try:
            self.gdf_soils = gpd.read_file(self.villages_zip, layer='OKri_Soils')
            print("Loaded soil layers for enrichment.")
        except:
            self.gdf_soils = None
        
        print(f"Loaded {len(self.df_pz)} piezometer records.")
        print(f"Loaded {len(self.df_pumping)} pumping records.")
        print(f"Loaded {len(self.gdf_villages)} village geometries.")

    # --- STEP 2: DATA PREPROCESSING ---
    def preprocess_data(self):
        print("Step 2: Preprocessing Data...")
        
        # 1. Clean Piezometer Data (Melt date columns)
        # Identify date columns (they look like datetime objects or strings)
        id_cols = ['SNo', 'ID', 'District', 'Mandal Name', 'Village Name', 'Location\n(Premises)', 
                   'Project', 'Total \nDepth \nin m', 'Principal Aquifer', 'MSL in meters', 
                   'Latitude \n(Decimal Degrees)', 'Longitude \n(Decimal Degrees)']
        
        date_cols = [c for c in self.df_pz.columns if isinstance(c, pd.Timestamp) or '202' in str(c)]
        
        df_pz_long = self.df_pz.melt(
            id_vars=id_cols, 
            value_vars=date_cols, 
            var_name='Date', 
            value_name='GW_Level'
        )
        
        # Rename columns for convenience
        df_pz_long = df_pz_long.rename(columns={
            'Latitude \n(Decimal Degrees)': 'Lat',
            'Longitude \n(Decimal Degrees)': 'Lon',
            'Principal Aquifer': 'Soil_Type',
            'Mandal Name': 'Mandal',
            'Village Name': 'Village'
        })
        
        # Convert types
        df_pz_long['Date'] = pd.to_datetime(df_pz_long['Date'])
        df_pz_long['GW_Level'] = pd.to_numeric(df_pz_long['GW_Level'], errors='coerce')
        df_pz_long = df_pz_long.dropna(subset=['GW_Level', 'Lat', 'Lon'])
        
        # 2. Handle Seasonal features
        df_pz_long['Month'] = df_pz_long['Date'].dt.month
        df_pz_long['Year'] = df_pz_long['Date'].dt.year
        df_pz_long['Season'] = df_pz_long['Month'].apply(lambda x: 'Monsoon' if 6 <= x <= 9 else 'Dry')
        
        # 3. Encode Soil Types
        df_pz_long['Soil_Enc'] = df_pz_long['Soil_Type'].astype('category').cat.codes
        
        # 4. Normalize Rainfall (Simulate if not provided, or use project defaults)
        # Using a simple seasonal rainfall proxy based on Month
        df_pz_long['Rainfall'] = df_pz_long['Month'].apply(lambda x: 200 if 6 <= x <= 9 else 20)
        
        self.df_features = df_pz_long
        print(f"Preprocessed data: {len(self.df_features)} observations.")

    # --- STEP 3: SPATIAL MAPPING ---
    def spatial_mapping(self):
        print("Step 3: Spatial Mapping...")
        # Create GeoDataFrame for Piezometers
        geometry = [Point(xy) for xy in zip(self.df_features['Lon'], self.df_features['Lat'])]
        gdf_pz = gpd.GeoDataFrame(self.df_features, geometry=geometry, crs="EPSG:4326")
        
        # For each village, find nearest piezometer
        # Use projected CRS for accurate distance (UTM zone 44N for Andhra Pradesh)
        self.gdf_villages = self.gdf_villages.to_crs("EPSG:32644")
        gdf_pz_proj = gdf_pz.to_crs("EPSG:32644")
        
        # Add centroid to villages
        self.gdf_villages['centroid'] = self.gdf_villages.geometry.centroid
        
        # Calculate distance to nearest observation
        print("Calculating spatial features (Nearest Neighbor)...")
        # This is a simplification. In a real scenario, we'd do this per Month.
        # For this script, we'll join the piezometer locations to the villages.
        
        # Get unique piezometer locations
        unique_pz = gdf_pz_proj[['ID', 'geometry', 'Lat', 'Lon']].drop_duplicates('ID')
        
        # Fast nearest join
        print("Performing spatial join for nearest piezometers...")
        village_points = self.gdf_villages.copy()
        village_points['geometry'] = village_points.geometry.centroid
        
        # Ensure we have a unique ID for each village row
        village_points['_original_index'] = village_points.index
        
        nearest = gpd.sjoin_nearest(
            village_points, 
            unique_pz, 
            how="left", 
            distance_col="Dist_M"
        )
        
        # Clean up duplicates (in case of ties in distance)
        nearest = nearest.drop_duplicates(subset=['_original_index'])
        nearest = nearest.set_index('_original_index').sort_index()
        
        # Merge back to gdf_villages
        self.gdf_villages['Dist_KM'] = nearest['Dist_M'].values / 1000.0
        # If 'ID' was unique to right side, it won't have _right suffix
        id_col = 'ID_right' if 'ID_right' in nearest.columns else 'ID'
        self.gdf_villages['Nearest_PZ_ID'] = nearest[id_col].values
        
        print("Spatial mapping complete.")

    # --- STEP 4: FEATURE ENGINEERING ---
    def feature_engineering(self):
        print("Step 4: Feature Engineering...")
        # Lags
        self.df_features = self.df_features.sort_values(['ID', 'Date'])
        self.df_features['Rainfall_Lag1'] = self.df_features.groupby('ID')['Rainfall'].shift(1).fillna(0)
        self.df_features['GW_Lag1'] = self.df_features.groupby('ID')['GW_Level'].shift(1)
        
        # Average GW Level within Mandal (as a proxy for regional average)
        mandal_avg = self.df_features.groupby(['Mandal', 'Date'])['GW_Level'].transform('mean')
        self.df_features['Mandal_Avg_GW'] = mandal_avg
        
        # Handle missing GW_Lag1 with Mandal_Avg_GW
        self.df_features['GW_Lag1'] = self.df_features['GW_Lag1'].fillna(self.df_features['Mandal_Avg_GW'])
        
        # Final set of features for training
        self.train_cols = ['Lat', 'Lon', 'Month', 'Soil_Enc', 'Rainfall', 'Rainfall_Lag1', 'GW_Lag1', 'Mandal_Avg_GW']
        self.target_col = 'GW_Level'
        
        self.df_features = self.df_features.dropna(subset=[self.target_col] + self.train_cols)
        print(f"Features ready for training: {self.df_features.shape}")

    # --- STEP 5 & 6: MODEL BUILDING & EVALUATION ---
    def build_and_evaluate(self):
        print("Step 5 & 6: Model Building and Evaluation...")
        X = self.df_features[self.train_cols]
        y = self.df_features[self.target_col]
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        models_to_train = {
            'Random Forest': RandomForestRegressor(n_estimators=100, random_state=42),
            'XGBoost': XGBRegressor(n_estimators=100, learning_rate=0.1, random_state=42),
            'Gradient Boosting': GradientBoostingRegressor(n_estimators=100, random_state=42)
        }
        
        for name, model in models_to_train.items():
            print(f"Training {name}...")
            model.fit(X_train, y_train)
            preds = model.predict(X_test)
            
            rmse = np.sqrt(mean_squared_error(y_test, preds))
            mae = mean_absolute_error(y_test, preds)
            r2 = r2_score(y_test, preds)
            
            self.models[name] = model
            self.metrics[name] = {'RMSE': rmse, 'MAE': mae, 'R2': r2}
            print(f"{name} -> RMSE: {rmse:.4f}, MAE: {mae:.4f}, R2: {r2:.4f}")

    # --- STEP 7: PREDICTION FOR MISSING VILLAGES ---
    def predict_missing(self):
        print("Step 7: Predicting Groundwater for missing villages...")
        # Identify villages without piezometers
        # For demonstration, we'll use all villages in the gdf_villages and predict for May 2024
        
        prediction_date = pd.Timestamp('2024-05-01')
        predict_df = []
        
        # Get regional averages for May
        avg_gw_may = self.df_features[self.df_features['Month'] == 5]['GW_Level'].mean()
        
        mandal_col = self.mandal_name_col
        
        for idx, row in self.gdf_villages.iterrows():
            # Construct feature vector
            feat = {
                'Lat': row['centroid'].y, # Using centroid for Lat/Lon
                'Lon': row['centroid'].x,
                'Month': 5,
                'Soil_Enc': 0, # Default or map from Soil_Type if available
                'Rainfall': 20, # Typical May rainfall
                'Rainfall_Lag1': 20,
                'GW_Lag1': avg_gw_may, # Proxy
                'Mandal_Avg_GW': avg_gw_may
            }
            # Actually use real coordinates in 4326 for prediction logic if models were trained on them
            # Convert centroid back to 4326
            p = gpd.GeoSeries([row['centroid']], crs="EPSG:32644").to_crs("EPSG:4326")[0]
            feat['Lat'] = p.y
            feat['Lon'] = p.x
            
            predict_df.append({
                'Village': row[self.village_name_col],
                'Mandal': row.get(mandal_col, 'Unknown'),
                'Lat': p.y,
                'Lon': p.x,
                **feat
            })
            
        predict_df = pd.DataFrame(predict_df)
        best_model = self.models['XGBoost']
        
        predict_df['Predicted_GWL'] = best_model.predict(predict_df[self.train_cols])
        self.predictions = predict_df
        print(f"Generated predictions for {len(self.predictions)} villages.")

    # --- STEP 8: OUTPUT ---
    def save_output(self):
        print("Step 8: Saving results...")
        output_file = self.output_dir / "village_groundwater_predictions.xlsx"
        cols_to_save = ['Village', 'Mandal', 'Lat', 'Lon', 'Predicted_GWL']
        if 'Anomaly_Flag' in self.predictions.columns:
            cols_to_save.append('Anomaly_Flag')
        if 'Recommendation' in self.predictions.columns:
            cols_to_save.append('Recommendation')
            
        self.predictions[cols_to_save].to_excel(output_file, index=False)
        print(f"Results saved to {output_file}")

    # --- STEP 9: VISUALIZATION ---
    def visualize(self):
        print("Step 9: Generating Visualizations...")
        
        # 1. Actual vs Predicted (on test set)
        best_name = 'XGBoost'
        best_model = self.models[best_name]
        X = self.df_features[self.train_cols]
        y = self.df_features[self.target_col]
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        preds = best_model.predict(X_test)
        
        plt.figure(figsize=(10, 6))
        plt.scatter(y_test, preds, alpha=0.5, color='teal')
        plt.plot([y.min(), y.max()], [y.min(), y.max()], 'r--', lw=2)
        plt.xlabel('Actual Groundwater Level (m)')
        plt.ylabel('Predicted Groundwater Level (m)')
        plt.title(f'Actual vs Predicted - {best_name}')
        plt.savefig(self.output_dir / "actual_vs_predicted.png")
        
        # 2. Spatial Distribution
        plt.figure(figsize=(12, 10))
        sc = plt.scatter(self.predictions['Lon'], self.predictions['Lat'], c=self.predictions['Predicted_GWL'], cmap='RdYlBu_r', s=50, alpha=0.8)
        plt.colorbar(sc, label='Predicted Groundwater Level (m below ground)')
        plt.title('Predicted Groundwater Level Map (May 2024)')
        plt.xlabel('Longitude')
        plt.ylabel('Latitude')
        plt.savefig(self.output_dir / "groundwater_map.png")
        
        print("Visualizations saved.")

    # --- STEP 10: BONUS ---
    def bonus_features(self):
        print("Step 10: Anomaly Detection and Recharge Recommendations...")
        
        # 1. Anomaly Detection
        # Flag villages where predicted level > 1.5 * std dev from mean
        mean_gw = self.predictions['Predicted_GWL'].mean()
        std_gw = self.predictions['Predicted_GWL'].std()
        self.predictions['Anomaly_Flag'] = self.predictions['Predicted_GWL'].apply(lambda x: 'Critical Drop' if x > (mean_gw + 1.5 * std_gw) else 'Normal')
        
        # 2. Recharge Recommendation
        # High depth + Low rainfall + Sandy soil = High Recharge Priority
        def get_rec(row):
            if row['Predicted_GWL'] > 15 and row['Rainfall'] < 50:
                return "Urgent: Construct Recharge Shafts"
            elif row['Predicted_GWL'] > 10:
                return "Medium: Desilt MI Tanks"
            else:
                return "Low: Regular Monitoring"
                
        self.predictions['Recommendation'] = self.predictions.apply(get_rec, axis=1)
        
        # Resave with bonus info
        self.save_output()
        print("Bonus features added.")

    def run_pipeline(self):
        self.load_data()
        self.preprocess_data()
        self.spatial_mapping()
        self.feature_engineering()
        self.build_and_evaluate()
        self.predict_missing()
        self.visualize()
        self.bonus_features()
        print("\nPipeline execution complete successfully!")

if __name__ == "__main__":
    system = GroundwaterEstimationSystem(
        raw_data_dir=r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\data\raw',
        output_dir=r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\output\ml_expert'
    )
    system.run_pipeline()
