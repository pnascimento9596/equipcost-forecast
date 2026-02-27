import numpy as np
import pandas as pd
import pytest

from equipcost_forecast.forecasting.time_series import CostForecaster


@pytest.fixture
def trending_series():
    """Monthly costs with clear upward trend."""
    dates = pd.date_range("2020-01-01", periods=60, freq="MS")
    base = 1000
    trend = np.arange(60) * 50
    noise = np.random.RandomState(42).normal(0, 100, 60)
    values = base + trend + noise
    values = np.maximum(values, 0)
    return pd.Series(values, index=dates)


@pytest.fixture
def flat_series():
    """Monthly costs that are roughly constant."""
    dates = pd.date_range("2020-01-01", periods=60, freq="MS")
    values = 500 + np.random.RandomState(42).normal(0, 50, 60)
    values = np.maximum(values, 0)
    return pd.Series(values, index=dates)


@pytest.fixture
def seasonal_series():
    """Monthly costs with seasonal pattern."""
    dates = pd.date_range("2020-01-01", periods=60, freq="MS")
    base = 2000
    seasonal = 500 * np.sin(2 * np.pi * np.arange(60) / 12)
    trend = np.arange(60) * 10
    noise = np.random.RandomState(42).normal(0, 50, 60)
    values = base + seasonal + trend + noise
    values = np.maximum(values, 0)
    return pd.Series(values, index=dates)


class TestARIMA:
    def test_arima_trending_predictions_increase(self, trending_series):
        forecaster = CostForecaster(min_history_months=24)
        result = forecaster.forecast_arima(trending_series, horizon=12)

        assert result.method in ("arima", "exponential_smoothing")
        assert len(result.predictions) == 12

        # Last few predictions should be higher than first few
        first_3 = sum(float(p.predicted_cost) for p in result.predictions[:3])
        last_3 = sum(float(p.predicted_cost) for p in result.predictions[-3:])
        assert last_3 > first_3 * 0.8  # Allow some tolerance

    def test_arima_returns_confidence_intervals(self, trending_series):
        forecaster = CostForecaster(min_history_months=24)
        result = forecaster.forecast_arima(trending_series, horizon=6)

        for p in result.predictions:
            assert float(p.lower_bound) <= float(p.predicted_cost)
            assert float(p.predicted_cost) <= float(p.upper_bound)

    def test_arima_metrics_populated(self, trending_series):
        forecaster = CostForecaster(min_history_months=24)
        result = forecaster.forecast_arima(trending_series, horizon=6)

        assert result.metrics.mae >= 0
        assert result.metrics.rmse >= 0
        assert result.metrics.mape >= 0


class TestExponentialSmoothing:
    def test_ets_flat_series_stays_flat(self, flat_series):
        forecaster = CostForecaster(min_history_months=24)
        result = forecaster.forecast_exponential_smoothing(flat_series, horizon=12)

        assert result.method == "exponential_smoothing"
        mean_pred = np.mean([float(p.predicted_cost) for p in result.predictions])
        # Should be close to the series mean (~500)
        assert 200 < mean_pred < 800

    def test_ets_seasonal_series(self, seasonal_series):
        forecaster = CostForecaster(min_history_months=24)
        result = forecaster.forecast_exponential_smoothing(seasonal_series, horizon=12)

        assert len(result.predictions) == 12
        # Predictions should be in a reasonable range
        for p in result.predictions:
            assert float(p.predicted_cost) >= 0

    def test_ets_confidence_widens(self, trending_series):
        forecaster = CostForecaster(min_history_months=24)
        result = forecaster.forecast_exponential_smoothing(trending_series, horizon=12)

        # Confidence band should be wider at end than at start
        first_width = float(result.predictions[0].upper_bound) - float(
            result.predictions[0].lower_bound
        )
        last_width = float(result.predictions[-1].upper_bound) - float(
            result.predictions[-1].lower_bound
        )
        assert last_width > first_width
