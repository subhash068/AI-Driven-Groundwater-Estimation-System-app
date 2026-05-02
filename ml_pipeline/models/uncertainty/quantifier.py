import numpy as np

def estimate_uncertainty(predictions, model=None, method="ensemble_variance"):
    """
    Estimates uncertainty of predictions.
    For XGBoost, we can use ensemble variance (if trees are diverse) or quantile regression.
    For GNN, MC Dropout is preferred.
    
    Placeholder for returning a standard deviation or uncertainty range.
    """
    # Simple heuristic based on prediction scale, typically replaced by true quantile models.
    # In a real setup, we would return p95 - p05 or ensemble std dev.
    return np.abs(predictions * 0.15)  # 15% heuristic
