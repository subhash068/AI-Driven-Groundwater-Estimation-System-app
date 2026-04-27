import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import torch
from torch_geometric.data import Data
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

class SpatialGraphBuilder:
    def __init__(self, k_neighbors: int = 5):
        self.k_neighbors = k_neighbors
        self.scaler = StandardScaler()

    def build_graph(self, villages_gdf: gpd.GeoDataFrame, piezometers_gdf: gpd.GeoDataFrame, node_features: pd.DataFrame = None) -> Data:
        """
        Builds a PyTorch Geometric Data object combining piezometers and villages into a unified spatial graph.
        """
        # Ensure consistent CRS (use a projected CRS for accurate distance metrics, e.g., EPSG:32644)
        villages = villages_gdf.to_crs(epsg=32644)
        piezometers = piezometers_gdf.to_crs(epsg=32644)
        
        n_villages = len(villages)
        n_piezometers = len(piezometers)
        total_nodes = n_villages + n_piezometers
        
        # Create mapping arrays
        village_coords = np.array([(geom.x, geom.y) for geom in villages.geometry])
        piezometer_coords = np.array([(geom.x, geom.y) for geom in piezometers.geometry])
        
        all_coords = np.vstack([village_coords, piezometer_coords])
        
        # Node Type Mask: 0 = Village, 1 = Piezometer
        node_types = np.zeros(total_nodes, dtype=np.int64)
        node_types[n_villages:] = 1 
        
        # Compute KNN edges:
        # 1. Piezometers to Piezometers (Spatial relationship between sensors)
        # 2. Piezometers to Villages (Information flow from sensors to target)
        # 3. Villages to Villages (Spatial smoothing constraint)
        
        knn = NearestNeighbors(n_neighbors=self.k_neighbors + 1, metric='euclidean')
        knn.fit(all_coords)
        distances, indices = knn.kneighbors(all_coords)
        
        edge_index_list = []
        edge_weight_list = []
        
        for i in range(total_nodes):
            for j, dist in zip(indices[i], distances[i]):
                if i != j:  # Exclude self-loops
                    edge_index_list.append([i, j])
                    # Weight based on inverse distance
                    weight = 1.0 / (dist + 1e-6)
                    edge_weight_list.append(weight)
                    
        edge_index = torch.tensor(edge_index_list, dtype=torch.long).t().contiguous()
        edge_weight = torch.tensor(edge_weight_list, dtype=torch.float)
        
        # Node features
        if node_features is not None:
            # We assume node_features is aligned with [villages, piezometers]
            x = torch.tensor(self.scaler.fit_transform(node_features.values), dtype=torch.float)
        else:
            # Fallback: Just use coordinates as features
            x = torch.tensor(self.scaler.fit_transform(all_coords), dtype=torch.float)
            
        data = Data(x=x, edge_index=edge_index, edge_attr=edge_weight)
        data.pos = torch.tensor(all_coords, dtype=torch.float)
        data.node_type = torch.tensor(node_types, dtype=torch.long)
        
        return data
        
    def get_village_mask(self, data: Data) -> torch.Tensor:
        return data.node_type == 0
        
    def get_piezometer_mask(self, data: Data) -> torch.Tensor:
        return data.node_type == 1
