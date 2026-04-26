import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from tensorflow.keras.layers import LSTM, Dense
    from tensorflow.keras.models import Sequential
except Exception:  # pragma: no cover
    LSTM = None
    Dense = None
    Sequential = None


WINDOW = 6


def build_sequences(values: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for i in range(len(values) - window):
        X.append(values[i : i + window])
        y.append(values[i + window])
    return np.array(X), np.array(y)


def fallback_forecast(series: np.ndarray, horizon: int = 3) -> np.ndarray:
    last = float(np.mean(series[-WINDOW:]))
    return np.array([last for _ in range(horizon)], dtype=float)


def lstm_forecast(series: np.ndarray, horizon: int = 3) -> np.ndarray:
    if Sequential is None:
        return fallback_forecast(series, horizon)
    X, y = build_sequences(series, WINDOW)
    if len(X) < 8:
        return fallback_forecast(series, horizon)
    X = X.reshape((X.shape[0], X.shape[1], 1))

    model = Sequential(
        [
            LSTM(32, input_shape=(WINDOW, 1)),
            Dense(16, activation="relu"),
            Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mae")
    model.fit(X, y, epochs=25, batch_size=8, verbose=0)

    rolling = list(series[-WINDOW:])
    preds = []
    for _ in range(horizon):
        x_in = np.array(rolling[-WINDOW:]).reshape((1, WINDOW, 1))
        next_val = float(model.predict(x_in, verbose=0).ravel()[0])
        preds.append(next_val)
        rolling.append(next_val)
    return np.array(preds)


def run(input_csv: Path, out_csv: Path, horizon: int = 3) -> None:
    df = pd.read_csv(input_csv)
    req = {"village_id", "date", "groundwater_depth"}
    missing = req - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"])

    rows = []
    for village_id, grp in df.groupby("village_id"):
        grp = grp.sort_values("date")
        series = grp["groundwater_depth"].to_numpy(dtype=float)
        if len(series) < WINDOW + 3:
            continue
        preds = lstm_forecast(series, horizon=horizon)
        last_date = grp["date"].iloc[-1]
        std = float(np.std(series[-WINDOW:]) or 0.2)
        for idx, val in enumerate(preds, start=1):
            d = (last_date + pd.offsets.MonthBegin(idx)).normalize()
            rows.append(
                {
                    "village_id": village_id,
                    "forecast_date": d.date().isoformat(),
                    "predicted_groundwater_depth": round(float(val), 3),
                    "predicted_lower": round(float(val - 1.28 * std), 3),
                    "predicted_upper": round(float(val + 1.28 * std), 3),
                    "model_name": "lstm",
                }
            )
    out = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    print(f"Saved LSTM-style forecast rows: {len(out)} to {out_csv}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LSTM-based 3-month forecast generator")
    parser.add_argument("--input", type=Path, required=True, help="Input CSV with village_id/date/groundwater_depth")
    parser.add_argument("--out", type=Path, required=True, help="Output forecast CSV")
    parser.add_argument("--horizon", type=int, default=3, help="Forecast horizon in months")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.input, args.out, args.horizon)
