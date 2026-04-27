import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

class TimeSeriesAnomalyDetector:
    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        """
        Anomaly detector using Isolation Forest.
        contamination: The expected proportion of outliers in the data.
        """
        self.contamination = contamination
        self.model = IsolationForest(
            contamination=self.contamination, 
            random_state=random_state,
            n_estimators=100
        )
        self.scaler = StandardScaler()

    def fit_predict(self, df: pd.DataFrame, value_col: str = 'depth', time_col: str = 'date', group_col: str = 'piezometer_id') -> pd.DataFrame:
        """
        Fits the model and predicts anomalies on time-series data.
        Returns the dataframe with an 'is_anomaly' boolean column.
        """
        df_out = df.copy()
        df_out['is_anomaly'] = False
        df_out['anomaly_score'] = 0.0

        if df_out.empty or value_col not in df_out.columns:
            return df_out

        # We extract rolling features to give the model temporal context
        # Process each piezometer independently
        for pid, group in df_out.groupby(group_col):
            if len(group) < 5: # Not enough data to find anomalies
                continue
                
            # Sort by time
            if time_col in group.columns:
                group = group.sort_values(time_col)
            
            idx = group.index
            values = group[value_col].values.reshape(-1, 1)
            
            # Simple features: the value itself, and the diff from previous time step
            diffs = np.diff(values, axis=0)
            diffs = np.insert(diffs, 0, 0).reshape(-1, 1)
            
            # Combine features
            features = np.hstack([values, diffs])
            features_scaled = self.scaler.fit_transform(features)
            
            # Fit and predict
            preds = self.model.fit_predict(features_scaled)
            scores = self.model.decision_function(features_scaled)
            
            # IsolationForest returns -1 for anomalies and 1 for inliers
            df_out.loc[idx, 'is_anomaly'] = (preds == -1)
            df_out.loc[idx, 'anomaly_score'] = scores

        return df_out
