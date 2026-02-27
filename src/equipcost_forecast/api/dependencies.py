from collections.abc import Generator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from equipcost_forecast.models.database import get_engine, get_session_factory

_engine: Engine | None = None
_session_factory = None


def _get_factory():
    global _engine, _session_factory
    if _session_factory is None:
        _engine = get_engine()
        _session_factory = get_session_factory(_engine)
    return _session_factory


def reset_factory() -> None:
    """Reset the cached engine/factory (used in tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    factory = _get_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
