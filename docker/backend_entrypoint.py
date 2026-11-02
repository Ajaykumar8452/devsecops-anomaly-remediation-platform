"""Seed the persistent SQLite volume once, then start the backend process."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def seed_database_if_needed() -> None:
    database_path = Path(os.environ.get("ALERT_DATABASE_PATH", "/app/data/alerts.db"))
    seed_path = Path(os.environ.get("ALERT_DATABASE_SEED_PATH", "/app/seed-data/alerts.db"))

    if database_path.exists():
        if database_path.stat().st_size == 0:
            raise RuntimeError(
                f"Persistent SQLite file is empty; refusing to overwrite it: {database_path}"
            )
        print(f"Persistent SQLite database already exists at {database_path}; leaving it unchanged.")
        return

    if not seed_path.is_file():
        print(f"No seed database at {seed_path}; the application will initialize a new database.")
        return

    database_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.", suffix=".seed", dir=database_path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        source_uri = seed_path.resolve().as_uri() + "?mode=ro"
        source = sqlite3.connect(source_uri, uri=True, timeout=10)
        destination = sqlite3.connect(temporary_path, timeout=10)
        try:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise sqlite3.DatabaseError("seed database failed SQLite integrity_check")
        finally:
            destination.close()
            source.close()

        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, database_path)
        print(f"Copied the existing SQLite database into persistent storage at {database_path}.")
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    seed_database_if_needed()
    if len(sys.argv) < 2:
        raise SystemExit("No backend command was supplied to the container entrypoint.")
    os.execvp(sys.argv[1], sys.argv[1:])
