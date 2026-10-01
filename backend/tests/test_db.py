from pathlib import Path

from sqlalchemy import text

from bedrock.core.db import make_engine


def test_sqlite_connections_enforce_foreign_keys(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path}/bedrock.db")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_sqlite_connections_use_wal(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path}/bedrock.db")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_missing_data_directory_is_created(tmp_path: Path) -> None:
    # A fresh Docker volume or checkout has no data/ yet.
    db_dir = tmp_path / "fresh" / "data"
    engine = make_engine(f"sqlite:///{db_dir}/bedrock.db")
    with engine.connect():
        pass
    assert (db_dir / "bedrock.db").exists()
