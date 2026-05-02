import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv

class SpatioTemporalTransformerGNN(nn.Module):
    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int = 3, 
                 seq_len: int = 1, num_heads: int = 4, dropout: float = 0.2, 
                 edge_dim: int = None, num_aquifers: int = 20):
        """
        out_channels=3 for Quantile Regression [5th, 50th, 95th percentiles]
        """
        super(SpatioTemporalTransformerGNN, self).__init__()
        
        self.seq_len = seq_len
        self.dropout = dropout
        self.hidden_channels = hidden_channels
        
        # 0. Physics-Informed Embeddings (Aquifer properties)
        # Learnable embeddings for 'Specific Yield' and 'Transmissivity'
        self.aquifer_embedding = nn.Embedding(num_aquifers, 8) 
        
        # 1. Spatial Component (GATv2)
        # We add the embedding dimension to in_channels
        self.gat1 = GATv2Conv(in_channels + 8, hidden_channels, heads=num_heads, concat=True, dropout=dropout, edge_dim=edge_dim)
        self.gat2 = GATv2Conv(hidden_channels * num_heads, hidden_channels, heads=1, concat=False, dropout=dropout, edge_dim=edge_dim)
        
        # 2. Temporal Component (Attention/Transformer)
        self.temporal_attention = nn.MultiheadAttention(
            embed_dim=hidden_channels,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True
        )
        
        # 3. PINN Layer (Physics-Informed Residual Block)
        # This layer specifically learns the delta between pure statistical prediction and mass balance
        self.pinn_layer = nn.Sequential(
            nn.Linear(hidden_channels + 3, hidden_channels), # +3 for (recharge, extraction, cpd)
            nn.ReLU(),
            nn.Linear(hidden_channels, 1) # Outputs a physics-based adjustment
        )
        
        self.norm = nn.LayerNorm(hidden_channels)
        self.fc1 = nn.Linear(hidden_channels, hidden_channels // 2)
        self.out = nn.Linear(hidden_channels // 2, out_channels)

    def forward(self, x, edge_index, edge_attr=None, aquifer_idx=None, physics_inputs=None):
        """
        x: (nodes, seq, features)
        aquifer_idx: (nodes,) indices of aquifer units
        physics_inputs: (nodes, 3) -> (net_recharge, extraction, cpd)
        """
        if x.dim() == 2:
            x = x.unsqueeze(1)
        
        num_nodes, seq_len, num_features = x.shape
        
        # Integrate Aquifer Embeddings
        if aquifer_idx is not None:
            aq_emb = self.aquifer_embedding(aquifer_idx) # (nodes, 8)
            aq_emb = aq_emb.unsqueeze(1).repeat(1, seq_len, 1) # (nodes, seq, 8)
            x = torch.cat([x, aq_emb], dim=-1)
        
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
        
        # Last Step
        h_final = combined_seq[:, -1, :]
        
        # PINN Adjustment
        if physics_inputs is not None:
            p_adj = self.pinn_layer(torch.cat([h_final, physics_inputs], dim=-1))
            # The PINN adjustment is added to the median prediction later or used in loss
        
        # Final layers
        x_out = F.relu(self.fc1(h_final))
        q_out = self.out(x_out) # (q5, q50, q95)
        
        return q_out

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
