import json
import warnings
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
from equipcost_forecast.models.orm import CostForecast
from equipcost_forecast.models.schemas import (
    ForecastResult,
    ModelMetrics,
    MonthlyForecastPoint,
)

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def _compute_metrics(actual: np.ndarray, predicted: np.ndarray) -> ModelMetrics:
    """Compute MAE, RMSE, and MAPE from actual vs predicted arrays."""
    errors = actual - predicted
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    nonzero = actual != 0
    if nonzero.sum() > 0:
        mape = float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100)
    else:
        mape = 0.0
    return ModelMetrics(mae=round(mae, 2), rmse=round(rmse, 2), mape=round(mape, 2))


class CostForecaster:
    """Time-series cost forecasting using ARIMA and Exponential Smoothing."""

    def __init__(self, min_history_months: int = 24):
        self.min_history_months = min_history_months

    def forecast_arima(
        self, cost_series: pd.Series, horizon: int = 36
    ) -> ForecastResult:
        """Fit ARIMA model and produce forecasts with confidence intervals.

        Args:
            cost_series: Monthly cost time series (DatetimeIndex).
            horizon: Forecast horizon in months.

        Returns:
            ForecastResult with predictions, bounds, and metrics.
        """
        from statsmodels.tsa.arima.model import ARIMA

        values = cost_series.values.astype(float)

        # Use in-sample fit for metrics (last 20% as validation)
        split = max(int(len(values) * 0.8), self.min_history_months // 2)
        train, test = values[:split], values[split:]

        try:
            model = ARIMA(values, order=(1, 1, 1))
            fit = model.fit()

            forecast = fit.get_forecast(steps=horizon)
            pred_mean = np.asarray(forecast.predicted_mean).flatten()
            conf_80 = np.asarray(forecast.conf_int(alpha=0.20))
            conf_95 = np.asarray(forecast.conf_int(alpha=0.05))

            # Compute metrics on in-sample fit
            if len(test) > 0:
                val_model = ARIMA(train, order=(1, 1, 1))
                val_fit = val_model.fit()
                val_pred = np.asarray(val_fit.forecast(steps=len(test))).flatten()
                metrics = _compute_metrics(test, val_pred)
            else:
                in_sample = np.asarray(fit.fittedvalues).flatten()
                metrics = _compute_metrics(values[1:], in_sample[1:])

        except Exception:
            return self.forecast_exponential_smoothing(cost_series, horizon)

        # Build prediction points
        last_date = cost_series.index[-1]
        predictions = []
        for i in range(horizon):
            month_date = last_date + pd.DateOffset(months=i + 1)
            pred_val = max(0, float(pred_mean[i]))
            lower = max(0, float(conf_80[i, 0]))
            upper = float(conf_95[i, 1])
            predictions.append(
                MonthlyForecastPoint(
                    month=month_date.date(),
                    predicted_cost=Decimal(str(round(pred_val, 2))),
                    lower_bound=Decimal(str(round(lower, 2))),
                    upper_bound=Decimal(str(round(upper, 2))),
                )
            )

        return ForecastResult(
            method="arima",
            horizon_months=horizon,
            predictions=predictions,
            metrics=metrics,
        )

    def forecast_exponential_smoothing(
        self, cost_series: pd.Series, horizon: int = 36
    ) -> ForecastResult:
        """Holt-Winters exponential smoothing forecast.

        Args:
            cost_series: Monthly cost time series (DatetimeIndex).
            horizon: Forecast horizon in months.

        Returns:
            ForecastResult with predictions and metrics.
        """
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        values = cost_series.values.astype(float)
        # Ensure all positive for multiplicative; add small offset if needed
        values = np.maximum(values, 0.01)

        split = max(int(len(values) * 0.8), 6)
        train, test = values[:split], values[split:]

        try:
            model = ExponentialSmoothing(
                values,
                trend="add",
                seasonal=None,
                initialization_method="estimated",
            )
            fit = model.fit(optimized=True)
            pred = fit.forecast(steps=horizon)

            if len(test) > 0:
                val_model = ExponentialSmoothing(
                    train,
                    trend="add",
                    seasonal=None,
                    initialization_method="estimated",
                )
                val_fit = val_model.fit(optimized=True)
                val_pred = val_fit.forecast(steps=len(test))
                metrics = _compute_metrics(test, val_pred)
            else:
                fitted = fit.fittedvalues
                metrics = _compute_metrics(values, fitted)

        except Exception:
            # Last-resort: simple mean forecast
            mean_val = float(np.mean(values))
            pred = np.full(horizon, mean_val)
            metrics = ModelMetrics(mae=0.0, rmse=0.0, mape=0.0)

        # Build predictions with simple confidence bands
        std = float(np.std(values))

        last_date = cost_series.index[-1]
        predictions = []
        for i in range(horizon):
            month_date = last_date + pd.DateOffset(months=i + 1)
            pred_val = max(0, float(pred[i]))
            # Widening confidence bands
            width = std * (1 + 0.1 * i)
            lower = max(0, pred_val - 1.28 * width)
            upper = pred_val + 1.96 * width
            predictions.append(
                MonthlyForecastPoint(
                    month=month_date.date(),
                    predicted_cost=Decimal(str(round(pred_val, 2))),
                    lower_bound=Decimal(str(round(lower, 2))),
                    upper_bound=Decimal(str(round(upper, 2))),
                )
            )

        return ForecastResult(
            method="exponential_smoothing",
            horizon_months=horizon,
            predictions=predictions,
            metrics=metrics,
        )

    def forecast_equipment(
        self,
        equipment_id: int,
        session: Session,
        horizon: int = 36,
        method: str = "auto",
    ) -> ForecastResult:
        """Run a forecast for a specific equipment item and store results.

        Args:
            equipment_id: The equipment to forecast.
            session: Database session.
            horizon: Months to forecast.
            method: "arima", "exponential_smoothing", or "auto".

        Returns:
            ForecastResult with predictions and metrics.
        """
        aggregator = CostAggregator(session)
        df = aggregator.get_cost_history(equipment_id)

        if df.empty or len(df) < self.min_history_months:
            # Not enough data — try with lower threshold or return ETS
            if len(df) >= 6:
                cost_series = df["total_cost"]
                result = self.forecast_exponential_smoothing(cost_series, horizon)
            else:
                raise ValueError(
                    f"Equipment {equipment_id} has insufficient cost history "
                    f"({len(df)} months, need at least 6)"
                )
        else:
            cost_series = df["total_cost"]
            if method == "arima" or method == "auto":
                result = self.forecast_arima(cost_series, horizon)
            else:
                result = self.forecast_exponential_smoothing(cost_series, horizon)

        # Compute TCO figures
        today = date.today()
        current_year_start = date(today.year, 1, 1)
        next_year_start = date(today.year + 1, 1, 1)
        next_year_end = date(today.year + 1, 12, 31)

        annual_tco_current = sum(
            float(r.total_cost or 0)
            for _, r in df.iterrows()
            if hasattr(r, "name") or True  # all rows
        )
        # Filter to current year from history
        if not df.empty:
            cy_mask = df.index >= pd.Timestamp(current_year_start)
            annual_tco_current = float(df.loc[cy_mask, "total_cost"].sum())
            cumulative = float(df["total_cost"].sum())
        else:
            annual_tco_current = 0.0
            cumulative = 0.0

        # Next year from forecast
        annual_tco_next = sum(
            float(p.predicted_cost)
            for p in result.predictions
            if next_year_start <= p.month <= next_year_end
        )

        # Store forecast in DB
        monthly_json = json.dumps(
            [
                {
                    "month": p.month.isoformat(),
                    "predicted_cost": float(p.predicted_cost),
                    "lower_bound": float(p.lower_bound),
                    "upper_bound": float(p.upper_bound),
                }
                for p in result.predictions
            ]
        )
        metrics_json = json.dumps(
            {
                "mae": result.metrics.mae,
                "rmse": result.metrics.rmse,
                "mape": result.metrics.mape,
            }
        )

        forecast_record = CostForecast(
            equipment_id=equipment_id,
            forecast_date=today,
            forecast_horizon_months=horizon,
            forecast_method=result.method,
            monthly_forecasts=monthly_json,
            annual_tco_current_year=Decimal(str(round(annual_tco_current, 2))),
            annual_tco_next_year=Decimal(str(round(annual_tco_next, 2))),
            cumulative_tco_to_date=Decimal(str(round(cumulative, 2))),
            projected_remaining_life_months=None,
            model_metrics=metrics_json,
        )
        session.add(forecast_record)
        session.flush()

        return result
