import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv

class SpatioTemporalTransformerGNN(nn.Module):
    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int = 3, 
                 seq_len: int = 1, num_heads: int = 4, dropout: float = 0.2, edge_dim: int = None):
        """
        out_channels=3 for Quantile Regression [5th, 50th, 95th percentiles]
        """
        super(SpatioTemporalTransformerGNN, self).__init__()
        
        self.seq_len = seq_len
        self.dropout = dropout
        self.hidden_channels = hidden_channels
        
        # 1. Spatial Component (GATv2)
        # edge_dim enables processing of physics-aware edge weights (distance, elevation, etc.)
        self.gat1 = GATv2Conv(in_channels, hidden_channels, heads=num_heads, concat=True, dropout=dropout, edge_dim=edge_dim)
        self.gat2 = GATv2Conv(hidden_channels * num_heads, hidden_channels, heads=1, concat=False, dropout=dropout, edge_dim=edge_dim)
        
        # 2. Temporal Component (Attention/Transformer)
        # Replacing LSTM with MultiheadAttention for better temporal dynamics
        self.temporal_attention = nn.MultiheadAttention(
            embed_dim=hidden_channels,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True
        )
        
        # Layer Norm for stability
        self.norm = nn.LayerNorm(hidden_channels)
        
        # 3. Output Head (Quantile Regression)
        self.fc1 = nn.Linear(hidden_channels, hidden_channels // 2)
        self.out = nn.Linear(hidden_channels // 2, out_channels)

    def forward(self, x, edge_index, edge_attr=None):
        if x.dim() == 2:
            x = x.unsqueeze(1)
        
        num_nodes, seq_len, num_features = x.shape
        
        # Spatial Processing
        spatial_embeddings = []
        for t in range(seq_len):
            xt = x[:, t, :]
            h = self.gat1(xt, edge_index, edge_attr=edge_attr)
            h = F.elu(h)
            h = self.gat2(h, edge_index, edge_attr=edge_attr)
            h = F.elu(h)
            spatial_embeddings.append(h.unsqueeze(1))
            
        combined_seq = torch.cat(spatial_embeddings, dim=1) # (nodes, seq, hidden)
        
        # Temporal Attention
        attn_out, _ = self.temporal_attention(combined_seq, combined_seq, combined_seq)
        combined_seq = self.norm(combined_seq + attn_out)
        
        # Pooling/Last Step
        last_step = combined_seq[:, -1, :]
        
        # Final layers
        x = F.relu(self.fc1(last_step))
        x = self.out(x) # [batch, 3] -> (q5, q50, q95)
        
        return x

    def physics_informed_loss(self, pred, edge_index, edge_attr, lambda_flow=0.1):
        """
        Loss = MSE + lambda * FlowConsistency
        FlowConsistency penalizes large differences between neighbors (spatial smoothness)
        
        Refinement: Use squared edge_attr to ensure only very strong connections 
        (same aquifer + close distance) enforce smoothing.
        """
        median_pred = pred[:, 1]
        
        row, col = edge_index
        diff = (median_pred[row] - median_pred[col])**2
        
        # squaring edge_attr (which is in [0, 1]) makes the flow constraint 
        # much more selective, preserving jumps across hydro-geological boundaries.
        selective_weights = edge_attr**2
        flow_loss = torch.mean(diff * selective_weights)
        
        return flow_loss * lambda_flow

    def quantile_loss(self, pred, target):
        """
        Pinball loss for quantiles [0.05, 0.5, 0.95]
        """
        quantiles = torch.tensor([0.05, 0.5, 0.95], device=pred.device)
        errors = target.unsqueeze(1) - pred
        loss = torch.max(quantiles * errors, (quantiles - 1) * errors)
        return torch.mean(loss)

def predict_with_uncertainty(model, x, edge_index, edge_attr=None, num_samples=10):
    """
    Monte Carlo Dropout + Quantile Regression ensemble
    """
    model.train() # Enable dropout
    preds = []
    with torch.no_grad():
        for _ in range(num_samples):
            preds.append(model(x, edge_index, edge_attr).unsqueeze(0))
            
    preds = torch.cat(preds, dim=0) # (samples, nodes, 3)
    
    # Final output: Mean of the medians, and the bounds
    mean_median = preds[:, :, 1].mean(dim=0)
    lower_bound = preds[:, :, 0].min(dim=0)[0]
    upper_bound = preds[:, :, 2].max(dim=0)[0]
    
    model.eval()
    return mean_median, lower_bound, upper_bound
