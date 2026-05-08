from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class PremiumStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._language_cache: dict[int, str] = {}
        self._thumb_cache: dict[int, str | None] = {}
        self._known_users: set[int] = set()
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    language TEXT NOT NULL DEFAULT 'pt',
                    is_blocked INTEGER NOT NULL DEFAULT 0,
                    plan TEXT NOT NULL DEFAULT 'free',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    user_id INTEGER PRIMARY KEY,
                    default_thumb_path TEXT,
                    keep_link_history INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT,
                    bytes_in INTEGER NOT NULL DEFAULT 0,
                    bytes_out INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS links (
                    link_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    public_url TEXT NOT NULL,
                    internal_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    expires_at INTEGER,
                    deleted_at INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cache (
                    cache_key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS allowed_groups (
                    chat_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_by INTEGER,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    job_id TEXT,
                    platform TEXT,
                    stage TEXT,
                    message TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS file_cache (
                    cache_key TEXT PRIMARY KEY,
                    public_url TEXT,
                    telegram_file_id TEXT,
                    filename TEXT,
                    size INTEGER NOT NULL DEFAULT 0,
                    internal_path TEXT,
                    expires_at INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS file_id_cache (
                    url_hash TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_user_updated ON jobs(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_links_user_created ON links(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_links_expiry ON links(expires_at, deleted_at);
                CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache(expires_at);
                CREATE INDEX IF NOT EXISTS idx_errors_created ON errors(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_file_cache_expiry ON file_cache(expires_at);
                CREATE INDEX IF NOT EXISTS idx_file_id_cache_created ON file_id_cache(created_at);
                """
            )

    def ensure_user(self, user_id: int, language: str = "pt") -> None:
        if user_id in self._known_users:
            self._language_cache.setdefault(user_id, language)
            return

        now = int(time.time())
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO users(user_id, language, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (user_id, language, now, now),
            )
            db.execute("INSERT OR IGNORE INTO preferences(user_id) VALUES(?)", (user_id,))
        self._known_users.add(user_id)
        self._language_cache[user_id] = language

    def get_language(self, user_id: int, fallback: str = "pt") -> str:
        cached = self._language_cache.get(user_id)
        if cached:
            return cached
        with self.connection() as db:
            row = db.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
        language = str(row["language"]) if row else fallback
        self._language_cache[user_id] = language
        if row:
            self._known_users.add(user_id)
        return language

    def set_language(self, user_id: int, language: str) -> None:
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO users(user_id, language, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET language=excluded.language, updated_at=excluded.updated_at
                """,
                (user_id, language, now, now),
            )
            db.execute("INSERT OR IGNORE INTO preferences(user_id) VALUES(?)", (user_id,))
        self._known_users.add(user_id)
        self._language_cache[user_id] = language

    def set_thumb(self, user_id: int, path: str | None) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO preferences(user_id, default_thumb_path)
                VALUES(?, ?)
                ON CONFLICT(user_id) DO UPDATE SET default_thumb_path=excluded.default_thumb_path
                """,
                (user_id, path),
            )
        self._thumb_cache[user_id] = path

    def get_thumb(self, user_id: int) -> str | None:
        if user_id in self._thumb_cache:
            return self._thumb_cache[user_id]
        with self.connection() as db:
            row = db.execute("SELECT default_thumb_path FROM preferences WHERE user_id=?", (user_id,)).fetchone()
        thumb = str(row["default_thumb_path"]) if row and row["default_thumb_path"] else None
        self._thumb_cache[user_id] = thumb
        return thumb

    def create_job(self, job_id: str, user_id: int, kind: str, title: str | None = None) -> None:
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO jobs(job_id, user_id, kind, status, title, created_at, updated_at)
                VALUES(?, ?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, user_id, kind, title, now, now),
            )

    def update_job(self, job_id: str, status: str, **values: Any) -> None:
        allowed = {"bytes_in", "bytes_out", "error", "title"}
        assignments = ["status=?", "updated_at=?"]
        params: list[Any] = [status, int(time.time())]
        for key, value in values.items():
            if key in allowed:
                assignments.append(f"{key}=?")
                params.append(value)
        params.append(job_id)
        with self.connection() as db:
            db.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id=?", params)

    def recent_jobs(self, user_id: int, limit: int = 6) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT job_id, kind, status, title, error, bytes_in, bytes_out, created_at, updated_at
                FROM jobs
                WHERE user_id=?
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def cache_get(self, key: str) -> dict[str, Any] | None:
        now = int(time.time())
        with self.connection() as db:
            row = db.execute("SELECT value FROM cache WHERE cache_key=? AND expires_at>?", (key, now)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return None

    def cache_set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO cache(cache_key, value, expires_at, created_at) VALUES(?, ?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), now + ttl_seconds, now),
            )

    def record_link(
        self,
        *,
        link_id: str,
        user_id: int,
        public_url: str,
        internal_path: str,
        filename: str,
        mime_type: str | None,
        size: int,
        sha256: str,
        expires_at: int | None,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO links(link_id, user_id, public_url, internal_path, filename, mime_type, size, sha256, expires_at, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (link_id, user_id, public_url, internal_path, filename, mime_type, size, sha256, expires_at, int(time.time())),
            )

    def delete_link(self, link_id: str, user_id: int | None = None) -> str | None:
        query = "SELECT internal_path FROM links WHERE link_id=? AND deleted_at IS NULL"
        params: tuple[Any, ...] = (link_id,)
        if user_id is not None:
            query += " AND user_id=?"
            params = (link_id, user_id)
        with self.connection() as db:
            row = db.execute(query, params).fetchone()
            if not row:
                return None
            db.execute("UPDATE links SET deleted_at=? WHERE link_id=?", (int(time.time()), link_id))
        return str(row["internal_path"])

    def recent_links(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT link_id, public_url, filename, size, created_at
                FROM links
                WHERE user_id=? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self.connection() as db:
            return {
                "users": int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
                "jobs": int(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]),
                "links": int(db.execute("SELECT COUNT(*) FROM links WHERE deleted_at IS NULL").fetchone()[0]),
                "errors": int(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]),
            }

    def set_group_status(self, chat_id: int, status: str, actor_id: int | None = None) -> None:
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO allowed_groups(chat_id, status, updated_by, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET status=excluded.status, updated_by=excluded.updated_by, updated_at=excluded.updated_at
                """,
                (chat_id, status, actor_id, now),
            )

    def group_status(self, chat_id: int) -> str | None:
        with self.connection() as db:
            row = db.execute("SELECT status FROM allowed_groups WHERE chat_id=?", (chat_id,)).fetchone()
        return str(row["status"]) if row else None

    def record_error(
        self,
        *,
        user_id: int | None,
        chat_id: int | None,
        job_id: str | None,
        platform: str | None,
        stage: str,
        message: str,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO errors(user_id, chat_id, job_id, platform, stage, message, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, chat_id, job_id, platform, stage, message[:1000], int(time.time())),
            )

    def recent_errors(self, limit: int = 8) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT user_id, chat_id, job_id, platform, stage, message, created_at
                FROM errors
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cleanup_cache(self) -> int:
        now = int(time.time())
        with self.connection() as db:
            cursor = db.execute("DELETE FROM cache WHERE expires_at<=?", (now,))
        return int(cursor.rowcount or 0)

    def file_id_get(self, url_hash: str) -> dict[str, str] | None:
        with self.connection() as db:
            row = db.execute("SELECT file_id, mode FROM file_id_cache WHERE url_hash=?", (url_hash,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE file_id_cache SET hit_count=hit_count+1 WHERE url_hash=?", (url_hash,))
        return {"file_id": str(row["file_id"]), "mode": str(row["mode"])}

    def file_id_set(self, url_hash: str, file_id: str, mode: str) -> None:
        now = int(time.time())
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO file_id_cache(url_hash, file_id, mode, created_at, hit_count)
                VALUES(?, ?, ?, ?, 0)
                ON CONFLICT(url_hash) DO UPDATE SET
                    file_id=excluded.file_id,
                    mode=excluded.mode,
                    created_at=excluded.created_at
                """,
                (url_hash, file_id, mode, now),
            )

    def file_id_delete(self, url_hash: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM file_id_cache WHERE url_hash=?", (url_hash,))

    def file_id_cleanup(self, max_age_days: int = 30) -> int:
        cutoff = int(time.time()) - max_age_days * 86400
        with self.connection() as db:
            cursor = db.execute("DELETE FROM file_id_cache WHERE created_at<?", (cutoff,))
        return int(cursor.rowcount or 0)

    def cleanup_expired_links(self) -> list[str]:
        now = int(time.time())
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT internal_path
                FROM links
                WHERE internal_path != ''
                  AND deleted_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at<=?
                """,
                (now,),
            ).fetchall()
            db.execute(
                """
                UPDATE links
                SET deleted_at=?
                WHERE deleted_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at<=?
                """,
                (now, now),
            )
        return [str(row["internal_path"]) for row in rows if row["internal_path"]]

    def audit(self, actor_id: int, action: str, details: str | None = None) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO audit(actor_id, action, details, created_at) VALUES(?, ?, ?, ?)",
                (actor_id, action, details, int(time.time())),
            )
