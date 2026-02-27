from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from equipcost_forecast.cli import app

runner = CliRunner()


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "equipcost-forecast" in result.output

    def test_init_db(self):
        with (
            patch("equipcost_forecast.models.database.get_engine"),
            patch("equipcost_forecast.models.database.init_db"),
        ):
            result = runner.invoke(app, ["init-db"])
            assert result.exit_code == 0
            assert "initialized" in result.output.lower()

    def test_aggregate(self):
        mock_session = MagicMock()
        mock_aggregator = MagicMock()
        mock_aggregator.compute_monthly_rollups.return_value = 42

        with (
            patch(
                "equipcost_forecast.forecasting.cost_aggregator.CostAggregator",
                return_value=mock_aggregator,
            ),
            patch("equipcost_forecast.models.database.get_engine"),
            patch("equipcost_forecast.models.database.get_session") as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(app, ["aggregate"])
            assert result.exit_code == 0
            assert "42" in result.output

    def test_serve_command_exists(self):
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "FastAPI" in result.output

    def test_dashboard_command_exists(self):
        result = runner.invoke(app, ["dashboard", "--help"])
        assert result.exit_code == 0
        assert "Streamlit" in result.output

    def test_analyze_command_exists(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0

    def test_report_command_exists(self):
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0

    def test_forecast_command_exists(self):
        result = runner.invoke(app, ["forecast", "--help"])
        assert result.exit_code == 0
        assert "horizon" in result.output.lower()

    def test_load_data_command_exists(self):
        result = runner.invoke(app, ["load-data", "--help"])
        assert result.exit_code == 0
