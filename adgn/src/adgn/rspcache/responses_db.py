"""Async SQLite-backed storage for OpenAI Responses proxy (S2 schema).

Implements the two-table schema:
 - responses(key PK, model, input_json, kwargs_json, response_summary_json, status, created_ts)
 - response_frames(id PK, key, seq, frame_json)

Provides async methods used by the proxy:
 - init()/close()
 - claim_key(key, model, input_obj, kwargs_obj) -> bool
 - get_status(key) -> str | None
 - get_complete_response(key) -> dict | None
 - append_frame(key, seq, frame_obj)
 - finalize_response(key, response_obj, summary_obj=None)
 - get_frames(key) -> list[dict]

Small, dependency: aiosqlite
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import aiosqlite
from platformdirs import user_cache_path


def _default_db_path() -> Path:
    """Determine per-user cache directory using platformdirs.

    Uses platformdirs.user_cache_path("adgn-llm") for cross-platform correctness
    while preserving a final subdirectory for the responses DB.
    """
    cache_dir = Path(user_cache_path("adgn-llm", appauthor=False))
    root = cache_dir / "openai-responses-db"
    root.mkdir(parents=True, exist_ok=True)
    return root / "responses.db"


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    model TEXT,
    input_json TEXT,
    kwargs_json TEXT,
    response_summary_json TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_ts INTEGER
);

CREATE TABLE IF NOT EXISTS response_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    seq INTEGER NOT NULL,
    frame_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_responses_model ON responses(model);
CREATE INDEX IF NOT EXISTS idx_responses_created_ts ON responses(created_ts);
CREATE INDEX IF NOT EXISTS idx_response_frames_key_seq ON response_frames(key, seq);
"""


class ResponsesDB:
    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(str(self._db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.executescript(CREATE_TABLES_SQL)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def claim_key(
        self,
        key: str,
        model: str,
        input_obj: Any,
        kwargs_obj: Any,
    ) -> bool:
        """Try to create a new responses row in 'in_progress' state. Return True if claimed (inserted).
        If the key already exists, return False.
        """
        assert self._conn is not None, "DB not initialized"
        created = int(time.time())
        input_json = json.dumps(input_obj, ensure_ascii=False)
        kwargs_json = json.dumps(kwargs_obj or {}, ensure_ascii=False)
        try:
            await self._conn.execute(
                (
                    "INSERT INTO responses (key, model, input_json, kwargs_json, status, created_ts) "
                    "VALUES (?, ?, ?, ?, 'in_progress', ?)"
                ),
                (key, model, input_json, kwargs_json, created),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_status(self, key: str) -> str | None:
        assert self._conn is not None, "DB not initialized"
        cur = await self._conn.execute(
            "SELECT status FROM responses WHERE key = ?",
            (key,),
        )
        row = await cur.fetchone()
        await cur.close()
        return row[0] if row else None

    async def get_complete_response(self, key: str) -> dict[str, Any] | None:
        """Return full response (summary JSON) if status == 'complete', else None."""
        assert self._conn is not None, "DB not initialized"
        cur = await self._conn.execute(
            "SELECT response_summary_json, status FROM responses WHERE key = ?",
            (key,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        resp_json_str, status = row
        if status != "complete":
            return None
        try:
            return json.loads(resp_json_str) if resp_json_str else None
        except json.JSONDecodeError:
            return None

    async def append_frame(self, key: str, seq: int, frame_obj: Any) -> None:
        assert self._conn is not None, "DB not initialized"
        frame_json = json.dumps(frame_obj, ensure_ascii=False)
        await self._conn.execute(
            "INSERT INTO response_frames (key, seq, frame_json) VALUES (?, ?, ?)",
            (key, seq, frame_json),
        )
        await self._conn.commit()

    async def finalize_response(
        self,
        key: str,
        response_obj: Any,
        summary_obj: Any | None = None,
    ) -> None:
        assert self._conn is not None, "DB not initialized"
        summary_json = json.dumps(summary_obj or response_obj or {}, ensure_ascii=False)
        await self._conn.execute(
            (
                "UPDATE responses SET status = 'complete', response_summary_json = ? WHERE key = ?"
            ),
            (summary_json, key),
        )
        # In case the row didn't exist (race), ensure it's present
        await self._conn.execute(
            (
                "INSERT OR IGNORE INTO responses (key, model, input_json, kwargs_json, "
                "response_summary_json, status, created_ts) VALUES (?, '', '', '', ?, 'complete', ?)"
            ),
            (key, summary_json, int(time.time())),
        )
        await self._conn.commit()

    async def get_frames(self, key: str) -> list[dict[str, Any]]:
        assert self._conn is not None, "DB not initialized"
        cur = await self._conn.execute(
            ("SELECT frame_json FROM response_frames WHERE key = ? ORDER BY seq"),
            (key,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [json.loads(frame_json) for (frame_json,) in rows]
