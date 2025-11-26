"""SQLite persistence layer for chat messages and ad assets.

Lightweight abstraction so we can later swap storage backend.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DB_FILENAME = "storage.sqlite"


class SQLitePersistence:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:  # auto commit
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL,
                    thread_id TEXT,
                    prompt TEXT,
                    image_path TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_assets_thread ON assets(thread_id, created_at)"
            )

    # -- Messages -----------------------------------------------------
    def save_message(self, thread_id: str, role: str, content: str) -> None:
        ts = datetime.utcnow().isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages(thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, role, content, ts),
            )

    def list_threads(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT thread_id, COUNT(*) as message_count, MIN(created_at) as first_at, MAX(created_at) as last_at
                FROM messages GROUP BY thread_id ORDER BY last_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
        return [
            {
                "thread_id": r[0],
                "message_count": r[1],
                "first_at": r[2],
                "last_at": r[3],
            }
            for r in rows
        ]

    def get_thread_messages(self, thread_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE thread_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?
                """,
                (thread_id, limit, offset),
            )
            rows = cur.fetchall()
        return [
            {"role": r[0], "content": r[1], "created_at": r[2]} for r in rows
        ]

    # -- Assets -------------------------------------------------------
    def save_asset(self, asset_id: str, thread_id: Optional[str], prompt: Optional[str], image_path: Optional[str], metadata: Dict[str, Any]) -> None:
        ts = datetime.utcnow().isoformat()
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO assets(asset_id, thread_id, prompt, image_path, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (asset_id, thread_id, prompt, image_path, metadata_json, ts),
            )

    def list_assets(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT asset_id, thread_id, prompt, image_path, metadata, created_at
                FROM assets ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
        assets: List[Dict[str, Any]] = []
        for r in rows:
            metadata = {}
            try:
                metadata = json.loads(r[4]) if r[4] else {}
            except Exception:  # noqa: BLE001
                metadata = {"_error": "metadata_parse_failed"}
            assets.append(
                {
                    "asset_id": r[0],
                    "thread_id": r[1],
                    "prompt": r[2],
                    "image_path": r[3],
                    "metadata": metadata,
                    "created_at": r[5],
                }
            )
        return assets

    # -- Pruning -------------------------------------------------------
    def prune(self, older_than_days: int, vacuum: bool = True) -> Dict[str, int]:
        """Delete messages and assets older than the given age.

        Returns counts of deleted rows. Uses ISO timestamps so lexical comparison works.
        """
        cutoff_dt = datetime.utcnow().timestamp() - older_than_days * 86400
        cutoff_iso = datetime.utcfromtimestamp(cutoff_dt).isoformat()
        with self._lock, self._conn:
            # Count candidates first
            msg_cur = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE created_at < ?",
                (cutoff_iso,),
            )
            msg_count = msg_cur.fetchone()[0]
            asset_cur = self._conn.execute(
                "SELECT COUNT(*) FROM assets WHERE created_at < ?",
                (cutoff_iso,),
            )
            asset_count = asset_cur.fetchone()[0]
            # Delete
            self._conn.execute("DELETE FROM messages WHERE created_at < ?", (cutoff_iso,))
            self._conn.execute("DELETE FROM assets WHERE created_at < ?", (cutoff_iso,))
            if vacuum:
                try:
                    self._conn.execute("VACUUM")
                except Exception:  # noqa: BLE001
                    pass
        return {"messages_deleted": msg_count, "assets_deleted": asset_count}


_persistence: SQLitePersistence | None = None


def init_persistence(base_dir: Path) -> SQLitePersistence:
    global _persistence
    if _persistence is None:
        storage_path = base_dir / DB_FILENAME
        _persistence = SQLitePersistence(storage_path)
    return _persistence


def get_persistence() -> SQLitePersistence:
    if _persistence is None:
        raise RuntimeError("Persistence not initialized")
    return _persistence
