import torch

def groundwater_balance_constraint(pred, rainfall, extraction):
    """
    Physics-guided constraint penalizing predictions that heavily violate
    the simple mass balance: delta GWL ~ (Rainfall - Extraction)
    
    This function returns a penalty term to be added to the loss function (e.g., GNN).
    """
    # Assuming units are roughly normalized or proportional
    # Recharge approximation: a fraction of rainfall
    estimated_recharge = rainfall * 0.2 
    expected_change = estimated_recharge - extraction
    
    # Penalty: Absolute difference between model predicted depth and expected physical shift
    penalty = torch.abs(pred - expected_change)
    return penalty.mean()
