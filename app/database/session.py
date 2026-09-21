from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import models as _models  # noqa: F401


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        str(settings.database_url),
        echo=settings.sql_echo,
        pool_pre_ping=True,
    )


def create_session() -> Session:
    """Build a session lazily so imports and isolated tests do not require `.env`."""

    return Session(bind=get_engine(), expire_on_commit=False)


def get_session() -> Generator[Session]:
    """Yield a transaction-scoped session for command-line consumers."""

    with create_session() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
