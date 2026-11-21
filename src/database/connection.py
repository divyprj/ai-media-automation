"""SQLite connection factory and context manager enforcing WAL mode and safety PRAGMAs."""

import os
import sqlite3
from typing import Optional
from contextlib import AbstractContextManager

from src.config import get_settings


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and configure a new SQLite connection with required PRAGMAs.

    Args:
        db_path: Path or SQLite URI to database. Defaults to Settings.database_url.

    Returns:
        Configured sqlite3.Connection with Row row_factory and PRAGMAs set.
    """
    if db_path is None:
        db_path = get_settings().database_url

    is_uri = db_path.startswith("file:")
    is_memory = db_path == ":memory:" or "mode=memory" in db_path

    if not is_memory and not is_uri:
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        uri=is_uri,
        timeout=10.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    # Execute system PRAGMAs
    if not is_memory:
        conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")

    return conn


class DBConnectionContext(AbstractContextManager):
    """Context manager and connection wrapper for SQLite operations."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = create_connection(self.db_path)
        return self._conn

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn is not None:
            if exc_type is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
            self._conn.close()
            self._conn = None
        return False

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __getattr__(self, name):
        return getattr(self.connection, name)


def get_db_connection(db_path: Optional[str] = None) -> DBConnectionContext:
    """Connection factory and context manager for SQLite database access.

    Usage:
        with get_db_connection(db_path) as conn:
            conn.execute(...)

        # Or direct usage:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        conn.close()
    """
    return DBConnectionContext(db_path)
