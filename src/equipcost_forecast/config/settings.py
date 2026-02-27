from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "sqlite:///./data/equipcost.db"
    app_name: str = "equipcost-forecast"
    debug: bool = False
    discount_rate: float = 0.08
    fiscal_year_start_month: int = 10  # October

    model_config = {"env_prefix": "EQUIPCOST_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
