import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATConv, global_mean_pool

class SpatioTemporalGNN(nn.Module):
    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int, num_heads: int = 2, dropout: float = 0.3):
        super(SpatioTemporalGNN, self).__init__()
        
        self.dropout = dropout
        
        # Spatial Graph Attention Layers
        self.gat1 = GATConv(in_channels, hidden_channels, heads=num_heads, concat=True, dropout=dropout)
        self.gat2 = GATConv(hidden_channels * num_heads, hidden_channels, heads=1, concat=False, dropout=dropout)
        
        # Temporal Component (LSTM)
        # We assume the node features contain time-series sequences. 
        # Alternatively, if node features are just static + lag columns (flattened),
        # we can just use dense layers. For true ST-GNN, let's add an LSTM layer 
        # that processes a sequence if we pass it 3D tensors. 
        # For simplicity in this architecture, we use a deep MLP after GNN, assuming 
        # temporal lags (t-1, t-7, t-30) are part of the `in_channels` features.
        
        self.fc1 = nn.Linear(hidden_channels, hidden_channels)
        self.fc2 = nn.Linear(hidden_channels, hidden_channels // 2)
        
        # Output layer for regression (groundwater level prediction)
        self.out = nn.Linear(hidden_channels // 2, out_channels)

    def forward(self, x, edge_index, edge_attr=None):
        """
        x: Node feature matrix of shape (num_nodes, num_node_features)
        edge_index: Graph connectivity matrix of shape (2, num_edges)
        edge_attr: Edge weights of shape (num_edges,)
        """
        
        # Graph Convolution (Spatial Message Passing)
        # Pass edge_attr if GAT allows edge features (depends on PyG version, GATv2Conv does better, 
        # but GATConv can take edge_attr in newer versions. We'll use edge_attr if needed, or omit for pure topology).
        x = self.gat1(x, edge_index, edge_attr=edge_attr)
        x = F.elu(x)
        x = F.dropout(x, p=self.dropout, training=self.training)
        
        x = self.gat2(x, edge_index, edge_attr=edge_attr)
        x = F.elu(x)
        
        # Fully Connected Layers (capturing combined Spatio-Temporal representations)
        x = self.fc1(x)
        x = F.relu(x)
        x = F.dropout(x, p=self.dropout, training=self.training)
        
        x = self.fc2(x)
        x = F.relu(x)
        
        return self.out(x)
        
    def predict_with_uncertainty(self, x, edge_index, edge_attr=None, num_samples=10):
        """
        Monte Carlo Dropout for uncertainty estimation.
        Returns the mean prediction and standard deviation (confidence interval).
        """
        self.train() # Enable dropout
        predictions = []
        with torch.no_grad():
            for _ in range(num_samples):
                preds = self.forward(x, edge_index, edge_attr)
                predictions.append(preds.unsqueeze(0))
                
        predictions = torch.cat(predictions, dim=0)
        mean_pred = predictions.mean(dim=0)
        std_pred = predictions.std(dim=0)
        
        self.eval() # Reset to eval mode
        return mean_pred, std_pred
