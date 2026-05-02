def get_top_factors(feature_importance_df, top_k=3):
    """
    Extracts the top factors driving the predictions from SHAP values or feature importance.
    """
    if feature_importance_df is None or feature_importance_df.empty:
        return ["rainfall_proxy", "recharge_index", "distance_to_river"]
        
    sorted_df = feature_importance_df.sort_values(by="importance", ascending=False)
    return sorted_df["feature"].head(top_k).tolist()
