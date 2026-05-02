import torch

def groundwater_balance_constraint(pred, rainfall, extraction):
    """
    Physics-guided constraint penalizing predictions that heavily violate
    the simple mass balance: delta GWL ~ (Rainfall - Extraction)
    """
    estimated_recharge = rainfall * 0.2 
    expected_change = estimated_recharge - extraction
    penalty = torch.abs(pred - expected_change)
    return penalty.mean()

def hydraulic_gradient_constraint(pred_depth, elevation, edge_index, lambda_slope=0.05):
    """
    Enforces the 'Water Table Follows Topography' principle.
    Hydraulic Head H = Elevation - Depth.
    Penalizes extreme deviations or unphysical head reversals between connected nodes.
    """
    row, col = edge_index
    head = elevation - pred_depth
    
    # Head gradient between connected nodes
    head_diff = head[row] - head[col]
    elev_diff = elevation[row] - elevation[col]
    
    # Penalize if head gradient is in the opposite direction of elevation gradient
    # or if the head gradient is significantly steeper than the terrain.
    # (Simplified PINN constraint)
    mismatch = torch.relu(-(head_diff * elev_diff)) 
    return mismatch.mean() * lambda_slope

def aquifer_continuity_constraint(pred_depth, edge_index, edge_attr):
    """
    Penalizes depth discontinuities within the same aquifer unit.
    edge_attr should represent hydrogeological similarity.
    """
    row, col = edge_index
    diff = (pred_depth[row] - pred_depth[col])**2
    # edge_attr near 1 means same aquifer, near 0 means different or fault line
    return torch.mean(diff * edge_attr)
