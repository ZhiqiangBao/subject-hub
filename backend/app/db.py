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
        if paper_cols and "released_at" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN released_at DATETIME"))
            conn.execute(text("UPDATE papers SET released_at = created_at WHERE released_at IS NULL"))
        if paper_cols and "grading_started_at" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN grading_started_at DATETIME"))
        if paper_cols and "scores_released_at" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN scores_released_at DATETIME"))
        if paper_cols and "opens_at" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN opens_at DATETIME"))
            conn.execute(text("UPDATE papers SET opens_at = released_at WHERE opens_at IS NULL AND released_at IS NOT NULL"))
        if paper_cols and "closes_at" not in paper_cols:
            conn.execute(text("ALTER TABLE papers ADD COLUMN closes_at DATETIME"))
            conn.execute(
                text(
                    "UPDATE papers SET closes_at = datetime(released_at, '+' || duration_minutes || ' minutes') "
                    "WHERE closes_at IS NULL AND released_at IS NOT NULL AND duration_minutes > 0"
                )
            )
        user_cols = columns("users")
        if user_cols and "group_id" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN group_id INTEGER"))
        if user_cols and "created_by" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN created_by INTEGER"))
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        group_cols = columns("student_groups")
        if not group_cols:
            conn.execute(
                text(
                    "CREATE TABLE student_groups ("
                    "id INTEGER PRIMARY KEY,"
                    "name VARCHAR(64) NOT NULL,"
                    "kind VARCHAR(16) NOT NULL DEFAULT 'group',"
                    "grade INTEGER,"
                    "parent_id INTEGER REFERENCES student_groups(id),"
                    "created_by INTEGER NOT NULL REFERENCES users(id),"
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
        elif "kind" not in group_cols or "parent_id" not in group_cols:
            conn.execute(text("ALTER TABLE student_groups RENAME TO student_groups_old"))
            conn.execute(
                text(
                    "CREATE TABLE student_groups ("
                    "id INTEGER PRIMARY KEY,"
                    "name VARCHAR(64) NOT NULL,"
                    "kind VARCHAR(16) NOT NULL DEFAULT 'group',"
                    "grade INTEGER,"
                    "parent_id INTEGER REFERENCES student_groups(id),"
                    "created_by INTEGER NOT NULL REFERENCES users(id),"
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            old = columns("student_groups_old")
            if "kind" in old:
                conn.execute(
                    text(
                        "INSERT INTO student_groups (id, name, kind, grade, parent_id, created_by, created_at) "
                        "SELECT id, name, kind, grade, parent_id, created_by, created_at FROM student_groups_old"
                    )
                )
            elif "grade" in old:
                conn.execute(
                    text(
                        "INSERT INTO student_groups (id, name, kind, grade, created_by, created_at) "
                        "SELECT id, name, CASE WHEN grade IS NOT NULL THEN 'class' ELSE 'group' END, "
                        "grade, created_by, created_at FROM student_groups_old"
                    )
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO student_groups (id, name, kind, created_by, created_at) "
                        "SELECT id, name, 'group', created_by, created_at FROM student_groups_old"
                    )
                )
            conn.execute(text("DROP TABLE student_groups_old"))
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS student_group_members ("
                "id INTEGER PRIMARY KEY,"
                "user_id INTEGER NOT NULL REFERENCES users(id),"
                "group_id INTEGER NOT NULL REFERENCES student_groups(id),"
                "UNIQUE(user_id, group_id)"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT OR IGNORE INTO student_group_members (user_id, group_id) "
                "SELECT id, group_id FROM users WHERE group_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS paper_audiences ("
                "id INTEGER PRIMARY KEY,"
                "paper_id INTEGER NOT NULL REFERENCES papers(id),"
                "group_id INTEGER NOT NULL REFERENCES student_groups(id),"
                "opens_at DATETIME,"
                "closes_at DATETIME,"
                "UNIQUE(paper_id, group_id)"
                ")"
            )
        )
        conn.execute(text("PRAGMA foreign_keys=ON"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
