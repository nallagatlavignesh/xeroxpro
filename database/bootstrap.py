"""Open (and if needed create/upgrade) the application database."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

import config
from database.connection import make_engine, make_session_factory, session_scope
from database.migrations.runner import migrate
from database.models import AppMetadata
from database.seed import seed_if_empty


def open_database(path: Path | str | None = None) -> tuple[Engine, sessionmaker[Session]]:
    """Migrate, then seed on first run. Raises SchemaTooNewError for a DB from a newer app version."""
    path = Path(path) if path else config.db_path()
    migrate(path)
    engine = make_engine(path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        seed_if_empty(session)
        row = session.query(AppMetadata).filter_by(key="app_version").one_or_none()
        if row is None:
            session.add(AppMetadata(key="app_version", value=config.APP_VERSION))
        else:
            row.value = config.APP_VERSION
    return engine, factory
