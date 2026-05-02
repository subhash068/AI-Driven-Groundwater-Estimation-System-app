import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

class Autoencoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 8):
        super(Autoencoder, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU()
        )
        self.decoder = nn.Sequential(
            nn.Linear(hidden_dim // 2, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, input_dim)
        )

    def forward(self, x):
        x = self.encoder(x)
        x = self.decoder(x)
        return x

class AdvancedAnomalyDetector:
    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        self.contamination = contamination
        self.iforest = IsolationForest(
            contamination=self.contamination, 
            random_state=random_state,
            n_estimators=200
        )
        self.scaler = StandardScaler()
        self.ae = None

    def fit_ae(self, data_scaled, epochs=50):
        input_dim = data_scaled.shape[1]
        self.ae = Autoencoder(input_dim)
        optimizer = torch.optim.Adam(self.ae.parameters(), lr=0.01)
        criterion = nn.MSELoss()
        
        data_tensor = torch.FloatTensor(data_scaled)
        
        self.ae.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            output = self.ae(data_tensor)
            loss = criterion(output, data_tensor)
            loss.backward()
            optimizer.step()

    def predict(self, df: pd.DataFrame, feature_cols: list) -> pd.DataFrame:
        df_out = df.copy()
        if df_out.empty: return df_out
        
        features = df_out[feature_cols].values
        features_scaled = self.scaler.fit_transform(features)
        
        # 1. Isolation Forest Prediction
        if_preds = self.iforest.fit_predict(features_scaled)
        df_out['is_anomaly_iforest'] = (if_preds == -1)
        
        # 2. Autoencoder Reconstruction Error
        if self.ae is None:
            self.fit_ae(features_scaled)
        
        self.ae.eval()
        with torch.no_grad():
            features_tensor = torch.FloatTensor(features_scaled)
            reconstructed = self.ae(features_tensor)
            mse = torch.mean((features_tensor - reconstructed)**2, dim=1).numpy()
            
        # Threshold for AE based on contamination percentile
        threshold = np.percentile(mse, 100 * (1 - self.contamination))
        df_out['is_anomaly_ae'] = (mse > threshold)
        df_out['anomaly_score_ae'] = mse
        
        # Final flag: Combined decision
        df_out['is_anomaly'] = df_out['is_anomaly_iforest'] | df_out['is_anomaly_ae']
        
        return df_out

class TimeSeriesAnomalyDetector:
    # Retaining for backward compatibility
    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        self.detector = AdvancedAnomalyDetector(contamination, random_state)

    def fit_predict(self, df: pd.DataFrame, value_col: str = 'depth', **kwargs) -> pd.DataFrame:
        # Simplified wrapper for standard use case
        return self.detector.predict(df, [value_col])
