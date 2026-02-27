from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from equipcost_forecast.models.database import (
    get_engine,
    get_session,
    get_session_factory,
    init_db,
)


class TestDatabase:
    def test_get_engine_returns_engine(self):
        engine = get_engine("sqlite:///:memory:")
        assert isinstance(engine, Engine)

    def test_get_session_factory(self):
        engine = get_engine("sqlite:///:memory:")
        factory = get_session_factory(engine)
        assert isinstance(factory, sessionmaker)

    def test_get_session_context_manager(self):
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with get_session(engine) as session:
            assert session is not None

    def test_init_db_creates_tables(self):
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        from sqlalchemy import inspect

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "equipment_registry" in tables
        assert "work_orders" in tables

    def test_get_engine_default(self):
        engine = get_engine()
        assert engine is not None

    def test_init_db_no_engine(self):
        init_db()
