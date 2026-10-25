from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, Session, create_engine

from jalrekha.core.settings import get_settings


settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.edge_db_path.parent.mkdir(parents=True, exist_ok=True)
settings.central_db_path.parent.mkdir(parents=True, exist_ok=True)

_sqlite_connect_args = {"check_same_thread": False, "timeout": 30}
# Pool sized for burst load (20+ concurrent /reports under offline-flush replay).
# Default SQLAlchemy pool_size=5/max_overflow=10 exhausts when RAG/forecast paths
# hold extra short-lived sessions per request.
_pool_kwargs = {"pool_size": 20, "max_overflow": 40, "pool_timeout": 30, "pool_recycle": 1800}
edge_engine = create_engine(
    f"sqlite:///{settings.edge_db_path}",
    echo=False,
    connect_args=_sqlite_connect_args,
    **_pool_kwargs,
)
central_engine = create_engine(
    f"sqlite:///{settings.central_db_path}",
    echo=False,
    connect_args=_sqlite_connect_args,
    **_pool_kwargs,
)



def init_db() -> None:
    import jalrekha.agent.models  # noqa: F401  (register agent tables)
    import jalrekha.models.domain  # noqa: F401

    SQLModel.metadata.create_all(edge_engine)
    SQLModel.metadata.create_all(central_engine)
    _sync_missing_columns(edge_engine)
    _sync_missing_columns(central_engine)



def get_session():
    with Session(edge_engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone edge-DB session for use outside the FastAPI request scope
    (background tasks, scripts). The caller is responsible for ``.commit()``."""
    session = Session(edge_engine)
    try:
        yield session
    finally:
        session.close()



def get_central_session():
    with Session(central_engine) as session:
        yield session


def _sync_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue

            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns or column.primary_key:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN {_render_column_definition(column, engine)}'
                connection.exec_driver_sql(ddl)


def _render_column_definition(column, engine: Engine) -> str:
    column_sql = f'"{column.name}" {column.type.compile(dialect=engine.dialect)}'
    default_literal = _render_default_literal(column)
    if default_literal is not None:
        column_sql += f" DEFAULT {default_literal}"
    if not column.nullable:
        column_sql += " NOT NULL"
    return column_sql


def _render_default_literal(column) -> str | None:
    if column.default is None:
        return None

    value = getattr(column.default, "arg", None)
    if callable(value):
        return None
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"
