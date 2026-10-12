"""Small SQLite store for corpus versions and folder ingestion manifests."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock


class CorpusState:
    """Persist monotonic corpus versions independently of Qdrant storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.access_lock = RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS corpus_state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL);"
                "INSERT OR IGNORE INTO corpus_state VALUES(1, 0);"
                "CREATE TABLE IF NOT EXISTS documents "
                "(folder TEXT NOT NULL, doc_id TEXT NOT NULL, PRIMARY KEY(folder, doc_id));"
                "CREATE TABLE IF NOT EXISTS cache_state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER NOT NULL);"
                "INSERT OR IGNORE INTO cache_state VALUES(1, 0);"
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open a transaction and always close its handle, including on Windows."""
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @property
    def version(self) -> int:
        """Return the latest successfully ingested corpus version."""
        with self.connection() as connection:
            return int(
                connection.execute("SELECT version FROM corpus_state WHERE id=1").fetchone()[0]
            )

    @property
    def cache_epoch(self) -> int:
        """Return the persisted permission-change invalidation epoch."""
        with self.connection() as connection:
            return int(connection.execute("SELECT epoch FROM cache_state WHERE id=1").fetchone()[0])

    def bump_cache_epoch(self) -> int:
        """Atomically invalidate all future semantic-cache entries."""
        with self.connection() as connection:
            connection.execute("UPDATE cache_state SET epoch=epoch+1 WHERE id=1")
            return int(connection.execute("SELECT epoch FROM cache_state WHERE id=1").fetchone()[0])
