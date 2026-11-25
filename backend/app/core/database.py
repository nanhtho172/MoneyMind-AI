from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

from backend.app.models.finance import Base
from backend.app.models.knowledge import KnowledgeAdmin, KnowledgeDocument, KnowledgeFile, KnowledgeIndex, KnowledgeRevision


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    options = {"connect_args": {"check_same_thread": False}}
    if url.database in {None, "", ":memory:"}:
        options["poolclass"] = StaticPool
    else:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, hide_parameters=True, **options)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        columns = connection.exec_driver_sql("PRAGMA table_info(chat_conversations)").all()
        if columns and "updated_at" not in {row[1] for row in columns}:
            connection.exec_driver_sql("ALTER TABLE chat_conversations ADD COLUMN updated_at DATETIME")
        Base.metadata.create_all(connection)


def migrate_knowledge_schema(engine: Engine) -> None:
    """Add the knowledge tables to an existing SQLite database without rewriting user data."""
    Base.metadata.create_all(engine, tables=[
        KnowledgeAdmin.__table__, KnowledgeDocument.__table__, KnowledgeRevision.__table__,
        KnowledgeIndex.__table__, KnowledgeFile.__table__,
    ])
