from __future__ import annotations

from typing import Any

import pandas as pd


REQUIRED_FIELDS = ["predicted_groundwater_level", "confidence"]


def validate_schema(records: list[dict[str, Any]]) -> None:
    for index, row in enumerate(records):
        for key in REQUIRED_FIELDS:
            if key not in row:
                raise ValueError(f"Missing field: {key} at record index {index}")
            value = row.get(key)
            if value is None:
                raise ValueError(f"Null field: {key} at record index {index}")


def validate_schema_dataframe(frame: pd.DataFrame) -> None:
    validate_schema(frame.to_dict(orient="records"))
