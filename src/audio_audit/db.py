from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path TEXT NOT NULL UNIQUE,
    labels_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    original_path TEXT NOT NULL,
    current_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    duration_seconds REAL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    tags_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    missing INTEGER NOT NULL DEFAULT 0,
    last_action_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(root_id) REFERENCES roots(id),
    UNIQUE(root_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_files_root_id ON files(root_id);
CREATE INDEX IF NOT EXISTS idx_files_root_status ON files(root_id, status);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    previous_state_json TEXT NOT NULL,
    new_state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(root_id) REFERENCES roots(id),
    FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE INDEX IF NOT EXISTS idx_events_root_id ON events(root_id, id DESC);
"""


class AuditStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_or_create_root(self, connection: sqlite3.Connection, root_path: str, now: str):
        row = connection.execute(
            "SELECT * FROM roots WHERE root_path = ?",
            (root_path,),
        ).fetchone()
        if row is not None:
            connection.execute(
                "UPDATE roots SET updated_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            return self.get_root(connection, row["id"])

        cursor = connection.execute(
            """
            INSERT INTO roots (root_path, labels_json, created_at, updated_at)
            VALUES (?, '[]', ?, ?)
            """,
            (root_path, now, now),
        )
        return self.get_root(connection, cursor.lastrowid)

    def get_root(self, connection: sqlite3.Connection, root_id: int):
        return connection.execute(
            "SELECT * FROM roots WHERE id = ?",
            (root_id,),
        ).fetchone()

    def update_root_labels(
        self, connection: sqlite3.Connection, root_id: int, labels_json: str, now: str
    ):
        connection.execute(
            """
            UPDATE roots
            SET labels_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (labels_json, now, root_id),
        )
        return self.get_root(connection, root_id)

    def list_files_by_relative(
        self, connection: sqlite3.Connection, root_id: int
    ) -> dict[str, sqlite3.Row]:
        rows = connection.execute(
            """
            SELECT *
            FROM files
            WHERE root_id = ?
            ORDER BY lower(relative_path), id
            """,
            (root_id,),
        ).fetchall()
        return {row["relative_path"]: row for row in rows}

    def list_files(self, connection: sqlite3.Connection, root_id: int):
        return connection.execute(
            """
            SELECT *
            FROM files
            WHERE root_id = ?
            ORDER BY lower(relative_path), id
            """,
            (root_id,),
        ).fetchall()

    def get_file(self, connection: sqlite3.Connection, file_id: int):
        return connection.execute(
            "SELECT * FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()

    def insert_file(self, connection: sqlite3.Connection, payload: dict):
        columns = ", ".join(payload.keys())
        placeholders = ", ".join("?" for _ in payload)
        cursor = connection.execute(
            f"INSERT INTO files ({columns}) VALUES ({placeholders})",
            tuple(payload.values()),
        )
        return self.get_file(connection, cursor.lastrowid)

    def update_file(self, connection: sqlite3.Connection, file_id: int, payload: dict):
        assignments = ", ".join(f"{column} = ?" for column in payload)
        connection.execute(
            f"UPDATE files SET {assignments} WHERE id = ?",
            tuple(payload.values()) + (file_id,),
        )
        return self.get_file(connection, file_id)

    def insert_event(
        self,
        connection: sqlite3.Connection,
        *,
        root_id: int,
        file_id: int,
        action: str,
        previous_state_json: str,
        new_state_json: str,
        created_at: str,
    ):
        connection.execute(
            """
            INSERT INTO events (
                root_id, file_id, action, previous_state_json, new_state_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (root_id, file_id, action, previous_state_json, new_state_json, created_at),
        )

    def get_last_event(self, connection: sqlite3.Connection, root_id: int):
        return connection.execute(
            """
            SELECT *
            FROM events
            WHERE root_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (root_id,),
        ).fetchone()

    def delete_event(self, connection: sqlite3.Connection, event_id: int) -> None:
        connection.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def get_stats(self, connection: sqlite3.Connection, root_id: int) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count_value
            FROM files
            WHERE root_id = ?
            GROUP BY status
            """,
            (root_id,),
        ).fetchall()

        stats = {
            "total": 0,
            "pending": 0,
            "approved": 0,
            "removed": 0,
            "skipped": 0,
            "missing": 0,
        }

        for row in rows:
            status = row["status"]
            count_value = int(row["count_value"])
            stats["total"] += count_value
            if status in stats:
                stats[status] = count_value

        missing_row = connection.execute(
            """
            SELECT COUNT(*) AS count_value
            FROM files
            WHERE root_id = ? AND missing = 1
            """,
            (root_id,),
        ).fetchone()
        stats["missing"] = int(missing_row["count_value"])
        return stats
