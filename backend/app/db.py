from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATA_DIR, ensure_dirs


class Base(DeclarativeBase):
    pass


ensure_dirs()
DB_PATH = DATA_DIR / "subject-hub.db"
engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def migrate() -> None:
    with engine.begin() as conn:
        def columns(table: str) -> set[str]:
            return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}

        user_cols = columns("users")
        if user_cols and "subjects_json" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN subjects_json VARCHAR(256) DEFAULT '*'"))
        paper_cols = columns("papers")
        if paper_cols and "duration_minutes" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN duration_minutes INTEGER DEFAULT 0"))
        if paper_cols and "sections_json" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN sections_json TEXT DEFAULT '[]'"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
