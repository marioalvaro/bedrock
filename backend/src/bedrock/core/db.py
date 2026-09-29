from collections.abc import Callable, Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from bedrock.core.config import Settings, get_settings


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite") and url != "sqlite:///:memory:" and ":memory:" not in url:
        db_path = url.removeprefix("sqlite:///")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def build_get_session(settings: Settings) -> Callable[[], Generator[Session, None, None]]:
    def _get_session() -> Generator[Session, None, None]:
        engine = make_engine(settings.resolved_database_url)
        session_factory = make_sessionmaker(engine)
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _get_session


def get_session() -> Generator[Session, None, None]:
    yield from build_get_session(get_settings())()
