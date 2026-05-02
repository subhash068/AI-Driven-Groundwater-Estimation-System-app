import numpy as np
import pandas as pd
import geopandas as gpd
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
        Builds a Physics-aware Spatial Graph.
        Edge Weight = f(distance, elevation_diff, attribute_similarity)
        """
        # Ensure consistent CRS (EPSG:32644 for India UTM zone)
        villages = villages_gdf.to_crs(epsg=32644)
        piezometers = piezometers_gdf.to_crs(epsg=32644)
        
        n_villages = len(villages)
        n_piezometers = len(piezometers)
        total_nodes = n_villages + n_piezometers
        
        village_coords = np.array([(geom.x, geom.y) for geom in villages.geometry])
        piezometer_coords = np.array([(geom.x, geom.y) for geom in piezometers.geometry])
        all_coords = np.vstack([village_coords, piezometer_coords])
        
        node_types = np.zeros(total_nodes, dtype=np.int64)
        node_types[n_villages:] = 1 
        
        knn = NearestNeighbors(n_neighbors=self.k_neighbors + 1, metric='euclidean')
        knn.fit(all_coords)
        distances, indices = knn.kneighbors(all_coords)
        
        edge_index_list = []
        edge_weight_list = []
        
        # Prepare attribute similarity factors if node_features are provided
        # We look for 'elevation_dem', 'lulc_code', 'soil_permeability'
        elevations = node_features['elevation_dem'].values if node_features is not None and 'elevation_dem' in node_features.columns else np.zeros(total_nodes)
        lulc = node_features['lulc_code'].values if node_features is not None and 'lulc_code' in node_features.columns else np.zeros(total_nodes)
        aquifers = node_features['aquifer_code'].values if node_features is not None and 'aquifer_code' in node_features.columns else np.zeros(total_nodes)
        geomorph = node_features['geomorphology_code'].values if node_features is not None and 'geomorphology_code' in node_features.columns else np.zeros(total_nodes)
        
        for i in range(total_nodes):
            for j, dist in zip(indices[i], distances[i]):
                if i != j:
                    edge_index_list.append([i, j])
                    
                    # 1. Distance Factor (Inverse Square)
                    w_dist = 1.0 / (dist**2 + 1e-6)
                    
                    # 2. Elevation Factor (Hydraulic gradient proxy)
                    # Penalize flow that goes "uphill" or across massive elevation drops (cliffs)
                    elev_diff = elevations[i] - elevations[j]
                    if elev_diff < -10.0:  # i is much lower than j, water doesn't flow uphill easily
                        w_elev = 0.1
                    else:
                        w_elev = np.exp(-abs(elev_diff) / 25.0) # Tighter decay constant
                    
                    # 3. LULC Similarity (Surface condition proxy)
                    w_lulc = 1.0 if lulc[i] == lulc[j] else 0.5
                    
                    # 4. Aquifer/Geology Similarity (Subsurface connectivity - CRITICAL PHYSICS)
                    # Groundwater does not easily cross from alluvial to hard rock boundaries
                    if aquifers[i] != aquifers[j] and aquifers[i] != 0 and aquifers[j] != 0:
                        w_aquifer = 0.05  # Severely penalize cross-aquifer communication
                    else:
                        w_aquifer = 1.5   # Boost intra-aquifer communication
                        
                    w_geomorph = 1.1 if geomorph[i] == geomorph[j] and geomorph[i] != 0 else 0.9
                    
                    # Combined Physics-aware weight
                    combined_weight = w_dist * w_elev * w_lulc * w_aquifer * w_geomorph
                    
                    # Prune edges with virtually no physical connection
                    if combined_weight < 0.05:
                        continue
                        
                    edge_weight_list.append(combined_weight)
                    
        # Normalize weights for stability
        edge_weights = np.array(edge_weight_list)
        if len(edge_weights) > 0:
            edge_weights = edge_weights / (np.max(edge_weights) + 1e-9)
            
        edge_index = torch.tensor(edge_index_list, dtype=torch.long).t().contiguous()
        edge_weight = torch.tensor(edge_weights, dtype=torch.float)
        
        if node_features is not None:
            x = torch.tensor(self.scaler.fit_transform(node_features.values), dtype=torch.float)
        else:
            x = torch.tensor(self.scaler.fit_transform(all_coords), dtype=torch.float)
            
        data = Data(x=x, edge_index=edge_index, edge_attr=edge_weight)
        data.pos = torch.tensor(all_coords, dtype=torch.float)
        data.node_type = torch.tensor(node_types, dtype=torch.long)
        
        return data
        
    def get_village_mask(self, data: Data) -> torch.Tensor:
        return data.node_type == 0
        
    def get_piezometer_mask(self, data: Data) -> torch.Tensor:
        return data.node_type == 1
