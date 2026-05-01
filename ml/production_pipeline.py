import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from xgboost import XGBRegressor
from sklearn.impute import KNNImputer
from sklearn.metrics import mean_absolute_error
import shap
from pathlib import Path

# Setup paths
RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("output/forecasts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def step1_ingestion():
    print("STEP 1: Data Ingestion & Schema Fixing...")
    
    # Load Water Level Data
    water_path = RAW_DIR / "PzWaterLevel_2024.xlsx"
    water_df_raw = pd.read_excel(water_path)
    
    # Identify index columns and date columns
    # Based on observation: First 12 columns are metadata
    id_cols = ['Village Name', 'Latitude \n(Decimal Degrees)', 'Longitude \n(Decimal Degrees)', 'Mandal Name', 'District']
    id_cols = [c for c in id_cols if c in water_df_raw.columns]
    
    date_cols = [c for c in water_df_raw.columns if isinstance(c, pd.Timestamp) or isinstance(c, (pd.Timestamp, str)) and str(c).startswith('19') or str(c).startswith('20')]
    
    # Melt the dataframe
    water_df = water_df_raw.melt(id_vars=id_cols, value_vars=date_cols, var_name='date', value_name='water_level')
    
    # Standardize names
    water_df = water_df.rename(columns={
        'Village Name': 'village',
        'Latitude \n(Decimal Degrees)': 'lat',
        'Longitude \n(Decimal Degrees)': 'lon',
        'Mandal Name': 'mandal'
    })
    
    # Clean water_level (handle strings like '4..31')
    water_df['water_level'] = water_df['water_level'].astype(str).str.replace('..', '.', regex=False)
    water_df['water_level'] = pd.to_numeric(water_df['water_level'], errors='coerce')
    
    water_df['date'] = pd.to_datetime(water_df['date'])
    water_df['year'] = water_df['date'].dt.year
    water_df['month'] = water_df['date'].dt.month
    
    # Load Pumping Data
    pump_path = RAW_DIR / "Pumping Data.xlsx"
    pump_df_raw = pd.read_excel(pump_path)
    
    # Clean Pumping Data (Mandal level, Monsoon/Non-Monsoon)
    # The first row often contains headers like 'Monsoon', 'Non-Monsoon'
    # We'll extract Mandal, Monsoon draft, and Non-Monsoon draft
    pump_clean = pump_df_raw.iloc[1:].copy()
    pump_clean.columns = ['SNo', 'mandal', 'village_hint', 'struct_type', 'num_wells', 'monsoon_draft', 'non_monsoon_draft']
    
    # Map Monsoon/Non-Monsoon to months
    # Monsoon: June to September (6, 7, 8, 9)
    # Non-Monsoon: Others
    
    def get_pumping(row):
        month = row['month']
        mandal = str(row['mandal']).strip().upper()
        
        mandal_pump = pump_clean[pump_clean['mandal'].str.strip().str.upper() == mandal]
        if mandal_pump.empty:
            return 0.0
        
        # Taking the average of structure types for that mandal
        if month in [6, 7, 8, 9]:
            return pd.to_numeric(mandal_pump['monsoon_draft'], errors='coerce').mean()
        else:
            return pd.to_numeric(mandal_pump['non_monsoon_draft'], errors='coerce').mean()

    # Apply pumping data (vectorized or grouped for performance)
    print("   Merging datasets...")
    # For now, let's just use a simple mapping
    mandal_pump_map = {}
    for _, r in pump_clean.iterrows():
        m = str(r['mandal']).strip().upper()
        mandal_pump_map[m] = {
            'monsoon': pd.to_numeric(r['monsoon_draft'], errors='coerce'),
            'non_monsoon': pd.to_numeric(r['non_monsoon_draft'], errors='coerce')
        }
        
    def map_pump(row):
        m = str(row['mandal']).strip().upper()
        if m in mandal_pump_map:
            if row['month'] in [6, 7, 8, 9]:
                return mandal_pump_map[m]['monsoon']
            else:
                return mandal_pump_map[m]['non_monsoon']
        return 0.0

    water_df['pumping'] = water_df.apply(map_pump, axis=1)
    
    return water_df

def step2_imputation(df):
    print("STEP 2: Missing Value Strategy (Confidence-Weighted 3-layer)...")
    df = df.copy()
    
    # Sort for temporal consistency
    df = df.sort_values(['village', 'date']).reset_index(drop=True)
    
    # Initialize Confidence Layer
    # Real observed = 1.0
    df['data_confidence'] = np.where(df['water_level'].isna(), 0.0, 1.0)
    df['is_imputed'] = df['water_level'].isna().astype(int)
    
    # Layer 1: Temporal Interpolation (Linear) - Confidence: 0.7
    print("   Layer 1: Temporal Interpolation (C=0.7)...")
    mask_l1 = df['water_level'].isna()
    df['water_level'] = df.groupby('village')['water_level'].transform(lambda x: x.interpolate(method='linear', limit_direction='both'))
    # Assign 0.7 to newly filled values
    df.loc[mask_l1 & df['water_level'].notna(), 'data_confidence'] = 0.7
    
    # Layer 2: Spatial KNN Imputation (Per month) - Confidence: 0.5
    print("   Layer 2: Spatial KNN (C=0.5)...")
    if df['water_level'].isna().any():
        for date, group in df.groupby('date'):
            if group['water_level'].isna().any():
                idx = group.index
                features_knn = ['lat', 'lon', 'pumping']
                
                train = group[group['water_level'].notna()]
                missing = group[group['water_level'].isna()]
                
                if not train.empty and not missing.empty:
                    from sklearn.neighbors import KNeighborsRegressor
                    knn = KNeighborsRegressor(n_neighbors=min(5, len(train)))
                    knn.fit(train[features_knn], train['water_level'])
                    
                    filled_vals = knn.predict(missing[features_knn])
                    df.loc[missing.index, 'water_level'] = filled_vals
                    df.loc[missing.index, 'data_confidence'] = 0.5
        
    # Layer 3: ML-Based Imputation (XGBoost Fallback) - Confidence: 0.3
    print("   Layer 3: ML-Based Imputation (C=0.3)...")
    if df['water_level'].isna().any():
        feature_cols = ['lat', 'lon', 'pumping', 'year', 'month']
        train = df[df['data_confidence'] >= 0.5] # Train on better data
        missing = df[df['water_level'].isna()]
        
        if not missing.empty:
            model = XGBRegressor(n_estimators=100)
            model.fit(train[feature_cols], train['water_level'])
            df.loc[missing.index, 'water_level'] = model.predict(missing[feature_cols])
            df.loc[missing.index, 'data_confidence'] = 0.3
            
    return df



def step3_features(df):
    print("STEP 3: Feature Engineering (Spatio-Temporal)...")
    df = df.sort_values(['village', 'date']).reset_index(drop=True)
    
    # Lag features
    print("   Creating lag features...")
    df['lag_1'] = df.groupby('village')['water_level'].shift(1)
    df['lag_3'] = df.groupby('village')['water_level'].shift(3)
    
    # Rolling stats
    print("   Creating rolling statistics...")
    df['rolling_mean_3'] = df.groupby('village')['water_level'].transform(lambda x: x.rolling(3).mean())
    
    # Seasonal encoding
    print("   Creating seasonal features...")
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    
    # Spatial Density Feature: Distance to nearest REAL sensor
    print("   Calculating distance to nearest sensor...")
    sensor_locs = df[df['data_confidence'] == 1.0][['lat', 'lon']].drop_duplicates().dropna()
    
    if not sensor_locs.empty:
        from sklearn.neighbors import NearestNeighbors
        nn = NearestNeighbors(n_neighbors=1)
        nn.fit(sensor_locs[['lat', 'lon']])
        
        village_locs = df[['village', 'lat', 'lon']].drop_duplicates('village').dropna(subset=['lat', 'lon'])
        if not village_locs.empty:
            dists, _ = nn.kneighbors(village_locs[['lat', 'lon']])
            dist_map = pd.Series(dists.ravel(), index=village_locs['village']).to_dict()
            df['dist_to_sensor'] = df['village'].map(dist_map).fillna(1.0)
        else:
            df['dist_to_sensor'] = 1.0
    else:
        df['dist_to_sensor'] = 1.0 # Default high distance
    
    return df



def step4_train(df):
    print("STEP 4: Quantile Regression Training (P10, P50, P90)...")
    
    features = [
        'lat', 'lon', 'pumping',
        'lag_1', 'lag_3', 'rolling_mean_3',
        'month_sin', 'month_cos',
        'is_imputed', 'dist_to_sensor'
    ]
    
    # Focus on High-Quality Data (2013-2024)
    train_df = df[df['year'] >= 2013].dropna(subset=features + ['water_level']).copy()
    weights = train_df['data_confidence'].values
    
    models = {}
    quantiles = [0.1, 0.5, 0.9]
    
    for q in quantiles:
        print(f"   Training Quantile {q}...")
        model = XGBRegressor(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.05,
            objective="reg:quantileerror",
            quantile_alpha=q,
            random_state=42
        )
        model.fit(train_df[features], train_df['water_level'], sample_weight=weights)
        models[q] = model
    
    return models, features

def step6a_spatial_validation(df, features):
    print("STEP 6a: Spatial Validation (Leave-One-Region-Out)...")
    
    # We use Mandals as regions
    mandals = df['mandal'].unique()
    # Sample 5 mandals for speed if many
    sample_mandals = np.random.choice(mandals, min(5, len(mandals)), replace=False)
    
    scores = []
    for m in sample_mandals:
        train_sub = df[(df['mandal'] != m) & (df['year'] >= 2013)].dropna(subset=features + ['water_level'])
        test_sub = df[(df['mandal'] == m) & (df['data_confidence'] == 1.0)].dropna(subset=features + ['water_level'])
        
        if test_sub.empty: continue
        
        model = XGBRegressor(n_estimators=100, random_state=42)
        model.fit(train_sub[features], train_sub['water_level'], sample_weight=train_sub['data_confidence'])
        
        preds = model.predict(test_sub[features])
        mae = mean_absolute_error(test_sub['water_level'], preds)
        scores.append(mae)
        print(f"   Holdout Mandal '{m}': MAE = {mae:.4f}")
        
    avg_spatial_mae = np.mean(scores)
    print(f"   Overall Spatial Generalization Score (MAE): {avg_spatial_mae:.4f}")
    return avg_spatial_mae



def step5_forecast(df, models, features):
    print("STEP 5: Forecasting (Recursive Quantile 2025-2027)...")
    future_years = [2025, 2026, 2027]
    
    # Metadata lookup
    village_meta = df[['village', 'lat', 'lon', 'mandal', 'District', 'dist_to_sensor', 'data_confidence']].drop_duplicates('village').sort_values('village').reset_index(drop=True)
    
    # Pre-calculate DQI (0-100)
    # Factor 1: Historical Data Confidence (60%)
    # Factor 2: Spatial Proximity to Sensors (40%)
    village_meta['dqi'] = (village_meta['data_confidence'] * 60) + (np.clip(1 - village_meta['dist_to_sensor']/0.2, 0, 1) * 40)
    village_meta['dqi'] = village_meta['dqi'].round(1)
    
    last_data = df.copy()
    predictions = []
    
    # Pre-calculate pumping map
    mandal_pump_map = {}
    for m in last_data['mandal'].unique():
        m_upper = str(m).strip().upper()
        mandal_data = last_data[last_data['mandal'] == m]
        mandal_pump_map[m_upper] = {
            'monsoon': mandal_data[mandal_data['month'].isin([6,7,8,9])]['pumping'].mean(),
            'non_monsoon': mandal_data[~mandal_data['month'].isin([6,7,8,9])]['pumping'].mean()
        }

    for year in future_years:
        print(f"   Forecasting Year {year}...")
        for month in range(1, 13):
            latest_v_data = last_data.sort_values(['village', 'date']).groupby('village').tail(3).copy()
            latest_v_data['rank'] = latest_v_data.groupby('village')['date'].rank(ascending=False, method='first')
            pivoted = latest_v_data.pivot(index='village', columns='rank', values='water_level')
            for r in [1.0, 2.0, 3.0]:
                if r not in pivoted.columns: pivoted[r] = np.nan
            pivoted = pivoted.reindex(village_meta['village'])
            
            lag_1 = pivoted[1.0].values
            lag_3 = pivoted[3.0].fillna(pivoted[1.0]).values
            rolling_mean_3 = pivoted[[1.0, 2.0, 3.0]].mean(axis=1).values
            
            pumping = []
            for m in village_meta['mandal']:
                m_upper = str(m).strip().upper()
                pumping.append(mandal_pump_map.get(m_upper, {'monsoon':0, 'non_monsoon':0})['monsoon' if month in [6,7,8,9] else 'non_monsoon'])
            
            temp_df = village_meta.copy()
            temp_df['year'], temp_df['month'] = year, month
            temp_df['date'] = pd.Timestamp(year=year, month=month, day=1)
            temp_df['pumping'], temp_df['lag_1'], temp_df['lag_3'] = pumping, lag_1, lag_3
            temp_df['rolling_mean_3'] = rolling_mean_3
            temp_df['month_sin'] = np.sin(2 * np.pi * month / 12)
            temp_df['month_cos'] = np.cos(2 * np.pi * month / 12)
            temp_df['is_imputed'] = 1
            
            # Predict P10, P50, P90
            temp_df['predicted_p10'] = models[0.1].predict(temp_df[features])
            temp_df['predicted_p50'] = models[0.5].predict(temp_df[features])
            temp_df['predicted_p90'] = models[0.9].predict(temp_df[features])
            
            # Set p50 as the main water_level for recursive lags
            temp_df['water_level'] = temp_df['predicted_p50']
            temp_df['predicted_water_level'] = temp_df['predicted_p50']
            
            last_data = pd.concat([last_data, temp_df], ignore_index=True)
            predictions.append(temp_df)
            
    return pd.concat(predictions, ignore_index=True)



def step6_validation(df, models, features):
    print("STEP 6: Real-Point Validation (P50 Median)...")
    
    # Use P50 model for standard MAE
    model = models[0.5]
    real_df = df[df['data_confidence'] == 1.0].dropna(subset=features + ['water_level'])
    test_set = real_df[real_df['year'] >= 2020]
    
    y_true = test_set['water_level']
    y_pred = model.predict(test_set[features])
    
    mae = mean_absolute_error(y_true, y_pred)
    print(f"   Validation on {len(test_set)} REAL points.")
    print(f"   Median (P50) MAE: {mae:.4f}")
    
    # Quantile Coverage Check (P10 to P90 should cover ~80% of data)
    y_p10 = models[0.1].predict(test_set[features])
    y_p90 = models[0.9].predict(test_set[features])
    coverage = ((y_true >= y_p10) & (y_true <= y_p90)).mean()
    print(f"   80% Interval Coverage: {coverage:.2%}")
    
    return mae

def step7_explainability(df, models, features):
    print("STEP 7: Explainability (SHAP Spatial Insights)...")
    model = models[0.5]
    train_df = df.dropna(subset=features + ['water_level'])
    sample = train_df[features].sample(min(500, len(train_df)), random_state=42)
    
    explainer = shap.Explainer(model)
    shap_values = explainer(sample)
    
    # SHAP Summary
    plt.figure(figsize=(10, 6))
    shap.summary_plot(shap_values, sample, show=False)
    plt.title('SHAP Feature Importance (P50 Model)')
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'shap_summary.png')
    plt.close()
    
    # Spatial SHAP Insight (Impact of 'dist_to_sensor' across District)
    plt.figure(figsize=(10, 6))
    shap.dependence_plot("dist_to_sensor", shap_values.values, sample, show=False)
    plt.title('Spatial Dependence: Distance to Sensor Impact')
    plt.savefig(OUTPUT_DIR / 'spatial_dependence.png')
    plt.close()


if __name__ == "__main__":
    df = step1_ingestion()
    df = step2_imputation(df)
    df = step3_features(df)
    models, features = step4_train(df)
    
    # Run Validations
    step6_validation(df, models, features)
    step6a_spatial_validation(df, features)
    step7_explainability(df, models, features)
    
    # Forecasting
    forecast_df = step5_forecast(df, models, features)
    
    # Final Output
    print("Saving refined research-grade results...")
    forecast_df.to_csv(OUTPUT_DIR / 'groundwater_forecast_2025_2027.csv', index=False)
    
    # Operational format (Winning features: P10/P50/P90 + DQI)
    operational_output = forecast_df[[
        'village', 'year', 'month', 
        'predicted_p10', 'predicted_p50', 'predicted_p90', 
        'dqi'
    ]].copy()
    operational_output.to_csv(OUTPUT_DIR / 'operational_forecast.csv', index=False)
    
    print(f"Pipeline complete. Outputs saved to {OUTPUT_DIR}")






