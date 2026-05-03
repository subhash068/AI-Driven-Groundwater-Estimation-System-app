
import asyncio
import json
from pathlib import Path
from backend.app.services import _standardize_village_payload

def test_normalization():
    print("Testing Smart Normalization Logic...")
    
    # Test Case 1: Alias Support (dtw)
    payload_dtw = {
        "village_id": 101,
        "village_name": "Test Village A",
        "dtw": 15.5
    }
    std_dtw = _standardize_village_payload(payload_dtw)
    print(f"Case 1 (dtw): Expected 15.5, Got {std_dtw['current_depth']}")
    assert std_dtw['current_depth'] == 15.5

    # Test Case 2: Temporal Series Fallback
    payload_series = {
        "village_id": 102,
        "village_name": "Test Village B",
        "monthly_depths": [10.1, 10.5, 11.2, None, 12.4]
    }
    std_series = _standardize_village_payload(payload_series)
    print(f"Case 2 (Series Fallback): Expected 12.4, Got {std_series['current_depth']}")
    assert std_series['current_depth'] == 12.4

    # Test Case 3: Prediction Alias (forecast_3m)
    payload_pred = {
        "village_id": 103,
        "village_name": "Test Village C",
        "forecast_3m": 22.8
    }
    std_pred = _standardize_village_payload(payload_pred)
    print(f"Case 3 (Prediction Alias): Expected 22.8, Got {std_pred['predicted_groundwater_level']}")
    assert std_pred['predicted_groundwater_level'] == 22.8

    print("\nSUCCESS: All normalization tests passed!")

if __name__ == "__main__":
    test_normalization()
