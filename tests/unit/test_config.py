from equipcost_forecast.config.settings import Settings, get_settings


class TestSettings:
    def test_defaults(self):
        settings = Settings()
        assert settings.database_url == "sqlite:///./data/equipcost.db"
        assert settings.discount_rate == 0.08
        assert settings.fiscal_year_start_month == 10
        assert settings.debug is False

    def test_get_settings_returns_instance(self):
        settings = get_settings()
        assert isinstance(settings, Settings)
        assert settings.app_name == "equipcost-forecast"
