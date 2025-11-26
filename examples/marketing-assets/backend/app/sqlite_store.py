"""SQLite-backed store for ChatKit threads and items.

Replaces MemoryStore to persist threads across server restarts.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from chatkit.store import NotFoundError, Store
from chatkit.types import (
    Attachment,
    Page,
    Thread,
    ThreadItem,
    ThreadMetadata,
    UserMessageItem,
    AssistantMessageItem,
    ClientToolCallItem,
    HiddenContextItem,
)

DB_FILENAME = "storage.sqlite"


class SQLiteStore(Store[dict[str, Any]]):
    """SQLite-backed store compatible with the ChatKit server interface."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path(__file__).parent.parent / DB_FILENAME
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            # Threads table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chatkit_threads (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Thread items table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chatkit_thread_items (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    role TEXT,
                    content TEXT,
                    raw_data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (thread_id) REFERENCES chatkit_threads(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_items_thread ON chatkit_thread_items(thread_id, created_at)"
            )

    @staticmethod
    def _coerce_thread_metadata(thread: ThreadMetadata | Thread) -> ThreadMetadata:
        """Return thread metadata without any embedded items."""
        has_items = isinstance(thread, Thread) or "items" in getattr(
            thread, "model_fields_set", set()
        )
        if not has_items:
            return thread.model_copy(deep=True)
        data = thread.model_dump()
        data.pop("items", None)
        return ThreadMetadata(**data).model_copy(deep=True)

    def _serialize_item(self, item: ThreadItem) -> Dict[str, Any]:
        """Serialize a ThreadItem to storable format."""
        item_type = type(item).__name__
        role = getattr(item, "role", None)
        content = None
        
        # Extract text content for search/display
        if hasattr(item, "content"):
            content_parts = []
            for part in getattr(item, "content", []) or []:
                text = getattr(part, "text", None)
                if text:
                    content_parts.append(text)
            if content_parts:
                content = "\n".join(content_parts)
        
        return {
            "id": item.id,
            "item_type": item_type,
            "role": role,
            "content": content,
            "raw_data": item.model_dump_json(),
            "created_at": (getattr(item, "created_at", None) or datetime.utcnow()).isoformat(),
        }

    def _deserialize_item(self, raw_data: str, item_type: str) -> ThreadItem:
        """Deserialize a ThreadItem from stored format."""
        data = json.loads(raw_data)
        
        # Map item_type to class
        type_map = {
            "UserMessageItem": UserMessageItem,
            "AssistantMessageItem": AssistantMessageItem,
            "ClientToolCallItem": ClientToolCallItem,
            "HiddenContextItem": HiddenContextItem,
        }
        
        cls = type_map.get(item_type)
        if cls is None:
            # Fallback: try to parse as generic
            raise NotFoundError(f"Unknown item type: {item_type}")
        
        return cls.model_validate(data)

    # -- Thread metadata -------------------------------------------------
    async def load_thread(self, thread_id: str, context: dict[str, Any]) -> ThreadMetadata:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, title, metadata, created_at FROM chatkit_threads WHERE id = ?",
                (thread_id,),
            )
            row = cur.fetchone()
        
        if not row:
            raise NotFoundError(f"Thread {thread_id} not found")
        
        metadata = json.loads(row[2]) if row[2] else {}
        created_at = datetime.fromisoformat(row[3]) if row[3] else datetime.utcnow()
        
        return ThreadMetadata(
            id=row[0],
            title=row[1],
            metadata=metadata,
            created_at=created_at,
        )

    async def save_thread(self, thread: ThreadMetadata, context: dict[str, Any]) -> None:
        metadata = self._coerce_thread_metadata(thread)
        now = datetime.utcnow().isoformat()
        metadata_json = json.dumps(getattr(metadata, "metadata", {}) or {})
        title = getattr(metadata, "title", None)
        created_at = (getattr(metadata, "created_at", None) or datetime.utcnow()).isoformat()
        
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO chatkit_threads (id, title, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                (metadata.id, title, metadata_json, created_at, now),
            )

    async def load_threads(
        self,
        limit: int,
        after: str | None,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadMetadata]:
        order_sql = "DESC" if order == "desc" else "ASC"
        
        with self._lock:
            if after:
                # Get the created_at of the 'after' thread for pagination
                cur = self._conn.execute(
                    "SELECT created_at FROM chatkit_threads WHERE id = ?",
                    (after,),
                )
                after_row = cur.fetchone()
                if after_row:
                    after_ts = after_row[0]
                    if order == "desc":
                        cur = self._conn.execute(
                            f"""
                            SELECT id, title, metadata, created_at FROM chatkit_threads
                            WHERE created_at < ? OR (created_at = ? AND id != ?)
                            ORDER BY created_at {order_sql}
                            LIMIT ?
                            """,
                            (after_ts, after_ts, after, limit + 1),
                        )
                    else:
                        cur = self._conn.execute(
                            f"""
                            SELECT id, title, metadata, created_at FROM chatkit_threads
                            WHERE created_at > ? OR (created_at = ? AND id != ?)
                            ORDER BY created_at {order_sql}
                            LIMIT ?
                            """,
                            (after_ts, after_ts, after, limit + 1),
                        )
                else:
                    cur = self._conn.execute(
                        f"SELECT id, title, metadata, created_at FROM chatkit_threads ORDER BY created_at {order_sql} LIMIT ?",
                        (limit + 1,),
                    )
            else:
                cur = self._conn.execute(
                    f"SELECT id, title, metadata, created_at FROM chatkit_threads ORDER BY created_at {order_sql} LIMIT ?",
                    (limit + 1,),
                )
            rows = cur.fetchall()
        
        threads = []
        for row in rows[:limit]:
            metadata = json.loads(row[2]) if row[2] else {}
            created_at = datetime.fromisoformat(row[3]) if row[3] else datetime.utcnow()
            threads.append(ThreadMetadata(
                id=row[0],
                title=row[1],
                metadata=metadata,
                created_at=created_at,
            ))
        
        has_more = len(rows) > limit
        next_after = threads[-1].id if has_more and threads else None
        
        return Page(data=threads, has_more=has_more, after=next_after)

    async def delete_thread(self, thread_id: str, context: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chatkit_thread_items WHERE thread_id = ?", (thread_id,))
            self._conn.execute("DELETE FROM chatkit_threads WHERE id = ?", (thread_id,))

    # -- Thread items ----------------------------------------------------
    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadItem]:
        order_sql = "DESC" if order == "desc" else "ASC"
        
        with self._lock:
            if after:
                cur = self._conn.execute(
                    "SELECT created_at FROM chatkit_thread_items WHERE id = ?",
                    (after,),
                )
                after_row = cur.fetchone()
                if after_row:
                    after_ts = after_row[0]
                    if order == "desc":
                        cur = self._conn.execute(
                            f"""
                            SELECT id, item_type, raw_data FROM chatkit_thread_items
                            WHERE thread_id = ? AND (created_at < ? OR (created_at = ? AND id != ?))
                            ORDER BY created_at {order_sql}
                            LIMIT ?
                            """,
                            (thread_id, after_ts, after_ts, after, limit + 1),
                        )
                    else:
                        cur = self._conn.execute(
                            f"""
                            SELECT id, item_type, raw_data FROM chatkit_thread_items
                            WHERE thread_id = ? AND (created_at > ? OR (created_at = ? AND id != ?))
                            ORDER BY created_at {order_sql}
                            LIMIT ?
                            """,
                            (thread_id, after_ts, after_ts, after, limit + 1),
                        )
                else:
                    cur = self._conn.execute(
                        f"""
                        SELECT id, item_type, raw_data FROM chatkit_thread_items
                        WHERE thread_id = ?
                        ORDER BY created_at {order_sql}
                        LIMIT ?
                        """,
                        (thread_id, limit + 1),
                    )
            else:
                cur = self._conn.execute(
                    f"""
                    SELECT id, item_type, raw_data FROM chatkit_thread_items
                    WHERE thread_id = ?
                    ORDER BY created_at {order_sql}
                    LIMIT ?
                    """,
                    (thread_id, limit + 1),
                )
            rows = cur.fetchall()
        
        items = []
        for row in rows[:limit]:
            try:
                item = self._deserialize_item(row[2], row[1])
                items.append(item)
            except Exception:
                # Skip items that can't be deserialized
                continue
        
        has_more = len(rows) > limit
        next_after = items[-1].id if has_more and items else None
        
        return Page(data=items, has_more=has_more, after=next_after)

    async def add_thread_item(
        self, thread_id: str, item: ThreadItem, context: dict[str, Any]
    ) -> None:
        serialized = self._serialize_item(item)
        
        with self._lock, self._conn:
            # Ensure thread exists
            self._conn.execute(
                """
                INSERT OR IGNORE INTO chatkit_threads (id, title, metadata, created_at, updated_at)
                VALUES (?, NULL, '{}', ?, ?)
                """,
                (thread_id, serialized["created_at"], serialized["created_at"]),
            )
            
            self._conn.execute(
                """
                INSERT INTO chatkit_thread_items (id, thread_id, item_type, role, content, raw_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    serialized["id"],
                    thread_id,
                    serialized["item_type"],
                    serialized["role"],
                    serialized["content"],
                    serialized["raw_data"],
                    serialized["created_at"],
                ),
            )

    async def save_item(self, thread_id: str, item: ThreadItem, context: dict[str, Any]) -> None:
        serialized = self._serialize_item(item)
        
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO chatkit_thread_items (id, thread_id, item_type, role, content, raw_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    item_type = excluded.item_type,
                    role = excluded.role,
                    content = excluded.content,
                    raw_data = excluded.raw_data
                """,
                (
                    serialized["id"],
                    thread_id,
                    serialized["item_type"],
                    serialized["role"],
                    serialized["content"],
                    serialized["raw_data"],
                    serialized["created_at"],
                ),
            )

    async def load_item(self, thread_id: str, item_id: str, context: dict[str, Any]) -> ThreadItem:
        with self._lock:
            cur = self._conn.execute(
                "SELECT item_type, raw_data FROM chatkit_thread_items WHERE id = ? AND thread_id = ?",
                (item_id, thread_id),
            )
            row = cur.fetchone()
        
        if not row:
            raise NotFoundError(f"Item {item_id} not found")
        
        return self._deserialize_item(row[1], row[0])

    async def delete_thread_item(
        self, thread_id: str, item_id: str, context: dict[str, Any]
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM chatkit_thread_items WHERE id = ? AND thread_id = ?",
                (item_id, thread_id),
            )

    # -- Files -----------------------------------------------------------
    async def upload_file(
        self,
        thread_id: str,
        file_name: str,
        data: bytes,
        content_type: str,
        context: dict[str, Any],
    ) -> Attachment:
        raise RuntimeError("File attachments are not supported by SQLite store.")

    async def download_file(
        self,
        thread_id: str,
        attachment: Attachment,
        context: dict[str, Any],
    ) -> bytes:
        raise RuntimeError("File attachments are not supported by SQLite store.")

    # -- Attachments (abstract methods from Store) -----------------------
    async def save_attachment(
        self,
        thread_id: str,
        attachment: Attachment,
        data: bytes,
        context: dict[str, Any],
    ) -> None:
        raise RuntimeError("File attachments are not supported by SQLite store.")

    async def load_attachment(
        self,
        thread_id: str,
        attachment: Attachment,
        context: dict[str, Any],
    ) -> bytes:
        raise RuntimeError("File attachments are not supported by SQLite store.")

    async def delete_attachment(
        self,
        thread_id: str,
        attachment: Attachment,
        context: dict[str, Any],
    ) -> None:
        raise RuntimeError("File attachments are not supported by SQLite store.")
