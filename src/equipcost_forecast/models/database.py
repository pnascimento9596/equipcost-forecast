import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from equipcost_forecast.models.orm import Base


def get_engine(url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine from DATABASE_URL or provided url."""
    db_url = url or os.environ.get("DATABASE_URL", "sqlite:///./data/equipcost.db")
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(db_url, connect_args=connect_args, echo=False)


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Return a sessionmaker bound to the given engine."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Yield a database session that auto-commits or rolls back."""
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Create all tables defined on Base."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
