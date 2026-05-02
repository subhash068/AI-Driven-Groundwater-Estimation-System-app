import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from prophet import Prophet
except Exception:  # pragma: no cover
    Prophet = None


REQUIRED_COLUMNS = [
    "village_id",
    "date",
    "groundwater_depth",
    "rainfall_mm",
    "draft_index",
    "season",
    "lulc_code",
]


def validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Input missing required columns: {missing}")


def prepare_regressors(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["season_kharif"] = (out["season"].str.lower() == "kharif").astype(int)
    out["season_rabi"] = (out["season"].str.lower() == "rabi").astype(int)
    return out


def prophet_forecast(group: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    group = prepare_regressors(group.sort_values("date"))
    train = group.rename(columns={"date": "ds", "groundwater_depth": "y"})
    train["ds"] = pd.to_datetime(train["ds"])

    model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.1,
    )
    for reg in ["rainfall_mm", "draft_index", "season_kharif", "season_rabi", "lulc_code"]:
        model.add_regressor(reg)
    model.fit(train[["ds", "y", "rainfall_mm", "draft_index", "season_kharif", "season_rabi", "lulc_code"]])

    future = model.make_future_dataframe(periods=months, freq="MS")
    latest = train.iloc[-1]
    future["rainfall_mm"] = latest["rainfall_mm"]
    future["draft_index"] = latest["draft_index"]
    future["season_kharif"] = 0
    future["season_rabi"] = 0
    future["lulc_code"] = latest["lulc_code"]

    month = future["ds"].dt.month
    future.loc[month.isin([6, 7, 8, 9, 10]), "season_kharif"] = 1
    future.loc[month.isin([11, 12, 1, 2, 3]), "season_rabi"] = 1

    fc = model.predict(future)
    out = fc[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(months).copy()
    out = out.rename(
        columns={
            "ds": "forecast_date",
            "yhat": "predicted_groundwater_depth",
            "yhat_lower": "predicted_lower",
            "yhat_upper": "predicted_upper",
        }
    )
    out["model_name"] = "prophet"
    return out


def fallback_moving_average(group: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    group = group.sort_values("date")
    last_date = pd.to_datetime(group["date"].iloc[-1])
    mean_value = float(group["groundwater_depth"].tail(6).mean())
    std = float(group["groundwater_depth"].tail(6).std() or 0.2)

    rows = []
    for i in range(1, months + 1):
        d = (last_date + pd.offsets.MonthBegin(i)).normalize()
        rows.append(
            {
                "forecast_date": d,
                "predicted_groundwater_depth": mean_value,
                "predicted_lower": mean_value - 1.28 * std,
                "predicted_upper": mean_value + 1.28 * std,
                "model_name": "moving_average",
            }
        )
    return pd.DataFrame(rows)


def run(input_csv: Path, output_csv: Path, months: int = 6) -> None:
    df = pd.read_csv(input_csv)
    validate(df)
    df["date"] = pd.to_datetime(df["date"])

    all_forecasts = []
    for village_id, group in df.groupby("village_id"):
        if len(group) < 12:
            continue

        if Prophet is not None:
            forecast = prophet_forecast(group, months=months)
        else:
            forecast = fallback_moving_average(group, months=months)

        forecast["village_id"] = village_id
        all_forecasts.append(forecast)

    result = pd.concat(all_forecasts, ignore_index=True) if all_forecasts else pd.DataFrame()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    print(f"Saved {len(result)} forecast rows to {output_csv}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Groundwater 6-month forecasting module")
    parser.add_argument("--input", type=Path, required=True, help="Input timeseries CSV")
    parser.add_argument("--out", type=Path, required=True, help="Output forecast CSV")
    parser.add_argument("--months", type=int, default=6, help="Forecast horizon in months")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.input, args.out, args.months)
