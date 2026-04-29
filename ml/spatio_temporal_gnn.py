import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv, global_mean_pool

class SpatioTemporalGNN(nn.Module):
    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int, 
                 seq_len: int = 1, num_heads: int = 4, dropout: float = 0.2):
        super(SpatioTemporalGNN, self).__init__()
        
        self.seq_len = seq_len
        self.dropout = dropout
        self.hidden_channels = hidden_channels
        
        # Spatial Graph Attention Layers (GATv2 for better dynamic weighting)
        self.gat1 = GATv2Conv(in_channels, hidden_channels, heads=num_heads, concat=True, dropout=dropout)
        self.gat2 = GATv2Conv(hidden_channels * num_heads, hidden_channels, heads=1, concat=False, dropout=dropout)
        
        # Temporal Component (LSTM)
        # We expect the GNN to produce a feature vector for each node at each time step.
        # LSTM will then process these sequences.
        self.lstm = nn.LSTM(
            input_size=hidden_channels,
            hidden_size=hidden_channels,
            num_layers=1,
            batch_first=True,
            dropout=dropout if seq_len > 1 else 0
        )
        
        # Final Regression Head
        self.fc1 = nn.Linear(hidden_channels, hidden_channels // 2)
        self.out = nn.Linear(hidden_channels // 2, out_channels)

    def forward(self, x, edge_index, edge_attr=None):
        """
        x: Node feature matrix. 
           Can be (num_nodes, num_features) for static, 
           or (num_nodes, seq_len, num_features) for temporal.
        edge_index: Graph connectivity (2, num_edges)
        """
        
        if x.dim() == 2:
            # Handle static input by adding a sequence dimension
            x = x.unsqueeze(1) # (num_nodes, 1, num_features)
        
        num_nodes, seq_len, num_features = x.shape
        
        # Process each time step through GNN
        spatial_embeddings = []
        for t in range(seq_len):
            xt = x[:, t, :] # (num_nodes, num_features)
            
            # Spatial convolution
            h = self.gat1(xt, edge_index, edge_attr=edge_attr)
            h = F.elu(h)
            h = F.dropout(h, p=self.dropout, training=self.training)
            
            h = self.gat2(h, edge_index, edge_attr=edge_attr)
            h = F.elu(h)
            
            spatial_embeddings.append(h.unsqueeze(1)) # (num_nodes, 1, hidden_channels)
            
        # Combine embeddings: (num_nodes, seq_len, hidden_channels)
        combined_seq = torch.cat(spatial_embeddings, dim=1)
        
        # Temporal processing via LSTM
        # LSTM output: (num_nodes, seq_len, hidden_size)
        lstm_out, _ = self.lstm(combined_seq)
        
        # Take the last time step's output for prediction
        last_step = lstm_out[:, -1, :] # (num_nodes, hidden_channels)
        
        # Output layers
        x = self.fc1(last_step)
        x = F.relu(x)
        x = self.out(x)
        
        return x
        
    def predict_with_uncertainty(self, x, edge_index, edge_attr=None, num_samples=10):
        """
        Monte Carlo Dropout for uncertainty estimation.
        """
        self.train()
        predictions = []
        with torch.no_grad():
            for _ in range(num_samples):
                preds = self.forward(x, edge_index, edge_attr)
                predictions.append(preds.unsqueeze(0))
                
        predictions = torch.cat(predictions, dim=0)
        mean_pred = predictions.mean(dim=0)
        std_pred = predictions.std(dim=0)
        
        self.eval()
        return mean_pred, std_pred
