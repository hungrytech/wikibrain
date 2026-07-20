from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .config import PRIVATE_FILE_MODE, ensure_private_directory
from .models import NormalizedEvent


SCHEMA_VERSION = 3


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context block, then release its file handle."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def stable_hash(*parts: str | None) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def turn_document_id(
    provider: str,
    session_id: str,
    turn_key: str,
    workspace: str,
) -> str:
    return "turn-" + stable_hash(
        provider,
        session_id,
        turn_key,
        workspace,
    )[:24]


def handoff_document_id(
    provider: str,
    session_id: str,
    workspace: str,
    summary: str,
) -> str:
    return "handoff-" + stable_hash(
        provider,
        session_id,
        workspace,
        summary,
    )[:24]


def explicit_memory_id(
    provider: str,
    session_id: str,
    turn_key: str,
    workspace: str,
) -> str:
    return "memory-" + stable_hash(
        "explicit",
        provider,
        session_id,
        turn_key,
        workspace,
    )[:24]


class BrainStore:
    def __init__(self, path: Path):
        self.path = path
        ensure_private_directory(path.parent)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=1.0,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 1000")
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    provider TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, session_id)
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_key TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    prompt TEXT,
                    response TEXT,
                    prompt_hash TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    document_id TEXT,
                    redaction_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (provider, session_id, turn_key),
                    FOREIGN KEY (provider, session_id)
                        REFERENCES sessions(provider, session_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_key TEXT,
                    name TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (provider, session_id)
                        REFERENCES sessions(provider, session_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tool_pointers (
                    event_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_key TEXT,
                    tool_name TEXT,
                    pointer_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (event_key) REFERENCES events(event_key)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS handoff_outbox (
                    event_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    redaction_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    document_id TEXT,
                    FOREIGN KEY (event_key) REFERENCES events(event_key)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS promotion_outbox (
                    provider TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (provider, session_id, turn_key),
                    FOREIGN KEY (provider, session_id, turn_key)
                        REFERENCES turns(provider, session_id, turn_key)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    provider TEXT,
                    session_id TEXT,
                    turn_key TEXT,
                    workspace TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS tombstones (
                    tombstone_id TEXT PRIMARY KEY,
                    selector TEXT NOT NULL UNIQUE,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_turns_workspace
                    ON turns(cwd, completed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_documents_workspace
                    ON documents(workspace, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(provider, session_id, created_at);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES('index_dirty', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) "
                "VALUES('index_generation', '0')"
            )
        try:
            os.chmod(self.path, PRIVATE_FILE_MODE)
        except OSError:
            pass

    @staticmethod
    def _has_tombstone(connection: sqlite3.Connection, selector: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM tombstones WHERE selector = ?",
                (selector,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _session_has_tombstone(
        connection: sqlite3.Connection,
        provider: str,
        session_id: str,
    ) -> bool:
        return BrainStore._has_tombstone(
            connection,
            f"session:{provider}:{session_id}",
        ) or BrainStore._has_tombstone(
            connection,
            f"session:{session_id}",
        )

    @staticmethod
    def _mark_dirty(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO metadata(key, value) VALUES('index_generation', '1')
            ON CONFLICT(key) DO UPDATE SET
                value = CAST(metadata.value AS INTEGER) + 1
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('index_dirty', '1')"
        )

    @staticmethod
    def _insert_tombstone(
        connection: sqlite3.Connection,
        selector: str,
        reason: str,
        receipt: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO tombstones(
                tombstone_id, selector, reason, created_at, receipt_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"forget-{stable_hash(selector)[:20]}",
                selector,
                reason,
                utc_now(),
                json.dumps(receipt, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _ensure_session(
        connection: sqlite3.Connection,
        provider: str,
        session_id: str,
        cwd: str,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO sessions(provider, session_id, cwd, started_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, session_id) DO UPDATE SET
                cwd = excluded.cwd,
                updated_at = excluded.updated_at
            """,
            (provider, session_id, cwd, timestamp, timestamp),
        )

    def capture_prompt(
        self,
        event: NormalizedEvent,
        prompt: str,
        redaction_count: int,
    ) -> tuple[bool, str]:
        timestamp = utc_now()
        prompt_hash = stable_hash(prompt)
        with self.transaction() as connection:
            if self._session_has_tombstone(
                connection, event.provider, event.session_id
            ):
                return False, event.turn_id or "forgotten"
            if self._has_tombstone(
                connection,
                (
                    f"source-prompt:{event.provider}:{event.session_id}:"
                    f"{prompt_hash}"
                ),
            ):
                return False, event.turn_id or "forgotten"
            if event.turn_id and self._has_tombstone(
                connection,
                (
                    f"source-turn:{event.provider}:{event.session_id}:"
                    f"{event.turn_id}"
                ),
            ):
                return False, event.turn_id or "forgotten"
            self._ensure_session(
                connection, event.provider, event.session_id, event.cwd, timestamp
            )
            turn_key = event.turn_id
            if not turn_key:
                cutoff = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
                recent = connection.execute(
                    """
                    SELECT turn_key FROM turns
                    WHERE provider = ? AND session_id = ? AND prompt_hash = ?
                      AND response IS NULL AND created_at >= ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (event.provider, event.session_id, prompt_hash, cutoff),
                ).fetchone()
                if recent:
                    return False, str(recent["turn_key"])
                turn_key = f"auto-{uuid.uuid4().hex[:20]}"

            event_key = stable_hash(
                event.provider,
                event.session_id,
                turn_key,
                event.name,
                prompt_hash,
            )
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_key, provider, session_id, turn_key, name, cwd,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    event.provider,
                    event.session_id,
                    turn_key,
                    event.name,
                    event.cwd,
                    json.dumps(event.raw_metadata, ensure_ascii=False),
                    timestamp,
                ),
            ).rowcount
            if not inserted:
                return False, turn_key
            connection.execute(
                """
                INSERT INTO turns(
                    provider, session_id, turn_key, cwd, prompt, prompt_hash,
                    created_at, redaction_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, session_id, turn_key) DO UPDATE SET
                    prompt = COALESCE(turns.prompt, excluded.prompt),
                    prompt_hash = COALESCE(turns.prompt_hash, excluded.prompt_hash),
                    redaction_count = turns.redaction_count + excluded.redaction_count
                """,
                (
                    event.provider,
                    event.session_id,
                    turn_key,
                    event.cwd,
                    prompt,
                    prompt_hash,
                    timestamp,
                    redaction_count,
                ),
            )
            return True, turn_key

    def capture_stop(
        self,
        event: NormalizedEvent,
        response: str,
        redaction_count: int,
    ) -> tuple[bool, sqlite3.Row | None]:
        timestamp = utc_now()
        response_hash = stable_hash(response)
        with self.transaction() as connection:
            if self._session_has_tombstone(
                connection, event.provider, event.session_id
            ):
                return False, None
            if self._has_tombstone(
                connection,
                (
                    f"source-response:{event.provider}:{event.session_id}:"
                    f"{response_hash}"
                ),
            ):
                return False, None
            if event.turn_id and self._has_tombstone(
                connection,
                (
                    f"source-turn:{event.provider}:{event.session_id}:"
                    f"{event.turn_id}"
                ),
            ):
                return False, None
            self._ensure_session(
                connection, event.provider, event.session_id, event.cwd, timestamp
            )
            turn_key = event.turn_id
            if not turn_key:
                # Claude Stop has no turn_id. A delayed duplicate can arrive
                # after the next prompt, so recognize an exact completed
                # response before claiming any newer open turn.
                row = connection.execute(
                    """
                    SELECT turn_key FROM turns
                    WHERE provider = ? AND session_id = ? AND response = ?
                    ORDER BY completed_at DESC, id DESC LIMIT 1
                    """,
                    (event.provider, event.session_id, response),
                ).fetchone()
                turn_key = str(row["turn_key"]) if row else None
            if not turn_key:
                row = connection.execute(
                    """
                    SELECT turn_key FROM turns
                    WHERE provider = ? AND session_id = ? AND response IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    (event.provider, event.session_id),
                ).fetchone()
                turn_key = str(row["turn_key"]) if row else None
            if not turn_key:
                turn_key = f"orphan-{stable_hash(response)[:20]}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO turns(
                        provider, session_id, turn_key, cwd, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event.provider,
                        event.session_id,
                        turn_key,
                        event.cwd,
                        timestamp,
                    ),
                )

            existing_turn = connection.execute(
                """
                SELECT * FROM turns
                WHERE provider = ? AND session_id = ? AND turn_key = ?
                """,
                (event.provider, event.session_id, turn_key),
            ).fetchone()
            if existing_turn is not None and existing_turn["response"] is not None:
                # A provider retry may carry a different rendering for the same
                # turn. Conversation evidence is immutable and first-write-wins.
                return False, existing_turn

            event_key = stable_hash(
                event.provider,
                event.session_id,
                turn_key,
                event.name,
                response_hash,
            )
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_key, provider, session_id, turn_key, name, cwd,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    event.provider,
                    event.session_id,
                    turn_key,
                    event.name,
                    event.cwd,
                    json.dumps(event.raw_metadata, ensure_ascii=False),
                    timestamp,
                ),
            ).rowcount
            if not inserted:
                existing = connection.execute(
                    """
                    SELECT * FROM turns
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (event.provider, event.session_id, turn_key),
                ).fetchone()
                return False, existing
            connection.execute(
                """
                UPDATE turns SET response = ?, completed_at = ?,
                    redaction_count = redaction_count + ?
                WHERE provider = ? AND session_id = ? AND turn_key = ?
                """,
                (
                    response,
                    timestamp,
                    redaction_count,
                    event.provider,
                    event.session_id,
                    turn_key,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM turns
                WHERE provider = ? AND session_id = ? AND turn_key = ?
                """,
                (event.provider, event.session_id, turn_key),
            ).fetchone()
            return True, row

    def capture_generic(self, event: NormalizedEvent) -> bool:
        timestamp = utc_now()
        event_key = stable_hash(
            event.provider,
            event.session_id,
            event.turn_id,
            event.name,
            event.tool_use_id,
            json.dumps(event.raw_metadata, ensure_ascii=False, sort_keys=True),
        )
        with self.transaction() as connection:
            if self._session_has_tombstone(
                connection, event.provider, event.session_id
            ):
                return False
            if self._has_tombstone(
                connection, f"source-event:{event_key}"
            ):
                return False
            self._ensure_session(
                connection, event.provider, event.session_id, event.cwd, timestamp
            )
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_key, provider, session_id, turn_key, name, cwd,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    event.provider,
                    event.session_id,
                    event.turn_id,
                    event.name,
                    event.cwd,
                    json.dumps(event.raw_metadata, ensure_ascii=False),
                    timestamp,
                ),
            ).rowcount
            if inserted and event.name == "PostToolUse":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO tool_pointers(
                        event_key, provider, session_id, turn_key, tool_name,
                        pointer_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_key,
                        event.provider,
                        event.session_id,
                        event.turn_id,
                        event.tool_name,
                        json.dumps(event.tool_pointer, ensure_ascii=False),
                        timestamp,
                    ),
                )
            return bool(inserted)

    def capture_handoff(
        self,
        event: NormalizedEvent,
        summary: str,
        redaction_count: int,
    ) -> tuple[bool, sqlite3.Row | None]:
        timestamp = utc_now()
        event_key = stable_hash(
            event.provider,
            event.session_id,
            event.name,
            stable_hash(summary),
        )
        with self.transaction() as connection:
            if self._session_has_tombstone(
                connection, event.provider, event.session_id
            ):
                return False, None
            if self._has_tombstone(
                connection, f"source-handoff:{event_key}"
            ):
                return False, None
            document_id = handoff_document_id(
                event.provider,
                event.session_id,
                event.cwd,
                summary,
            )
            if self._has_tombstone(
                connection, f"document:{document_id}"
            ):
                return False, None
            self._ensure_session(
                connection, event.provider, event.session_id, event.cwd, timestamp
            )
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_key, provider, session_id, turn_key, name, cwd,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    event.provider,
                    event.session_id,
                    event.turn_id,
                    event.name,
                    event.cwd,
                    json.dumps(event.raw_metadata, ensure_ascii=False),
                    timestamp,
                ),
            ).rowcount
            connection.execute(
                """
                INSERT OR IGNORE INTO handoff_outbox(
                    event_key, provider, session_id, workspace, summary,
                    redaction_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    event.provider,
                    event.session_id,
                    event.cwd,
                    summary,
                    redaction_count,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM handoff_outbox WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            return bool(inserted), row

    def pending_completed_turns(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT turns.* FROM turns
                    WHERE turns.completed_at IS NOT NULL
                      AND turns.document_id IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM tombstones
                          WHERE selector = (
                              'session:' || turns.provider || ':' || turns.session_id
                          )
                             OR selector = 'session:' || turns.session_id
                      )
                    ORDER BY turns.completed_at DESC, turns.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            )

    def pending_handoffs(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT handoff_outbox.* FROM handoff_outbox
                    WHERE handoff_outbox.document_id IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM tombstones
                          WHERE selector = (
                              'session:' || handoff_outbox.provider || ':'
                              || handoff_outbox.session_id
                          )
                             OR selector = 'session:' || handoff_outbox.session_id
                      )
                    ORDER BY handoff_outbox.created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            )

    def complete_handoff(self, event_key: str, document_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE handoff_outbox SET document_id = ?
                WHERE event_key = ?
                """,
                (document_id, event_key),
            )

    def queue_promotion(
        self,
        provider: str,
        session_id: str,
        turn_key: str,
    ) -> bool:
        with self.transaction() as connection:
            if self._session_has_tombstone(connection, provider, session_id):
                return False
            connection.execute(
                """
                INSERT OR IGNORE INTO promotion_outbox(
                    provider, session_id, turn_key, created_at
                )
                SELECT provider, session_id, turn_key, ?
                FROM turns
                WHERE provider = ? AND session_id = ? AND turn_key = ?
                  AND completed_at IS NOT NULL
                """,
                (utc_now(), provider, session_id, turn_key),
            )
            return (
                connection.execute(
                    """
                    SELECT 1 FROM promotion_outbox
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (provider, session_id, turn_key),
                ).fetchone()
                is not None
            )

    def complete_promotion(
        self,
        provider: str,
        session_id: str,
        turn_key: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                DELETE FROM promotion_outbox
                WHERE provider = ? AND session_id = ? AND turn_key = ?
                """,
                (provider, session_id, turn_key),
            )

    def pending_promotions(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT turns.* FROM promotion_outbox
                    JOIN turns USING(provider, session_id, turn_key)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM tombstones
                        WHERE selector = (
                            'session:' || turns.provider || ':' || turns.session_id
                        )
                           OR selector = 'session:' || turns.session_id
                    )
                    ORDER BY promotion_outbox.created_at ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            )

    def discard_handoff(self, event_key: str) -> None:
        """Remove a refused handoff and its source event without leaving plaintext."""
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM events WHERE event_key = ?",
                (event_key,),
            )

    def register_document(
        self,
        document_id: str,
        kind: str,
        path: Path,
        *,
        provider: str | None = None,
        session_id: str | None = None,
        turn_key: str | None = None,
        workspace: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        with self.transaction() as connection:
            session_forgotten = bool(
                session_id
                and provider
                and self._session_has_tombstone(
                    connection, provider, session_id
                )
            )
            document_forgotten = self._has_tombstone(
                connection, f"document:{document_id}"
            )
            if session_forgotten or document_forgotten:
                if session_forgotten and session_id and provider:
                    connection.execute(
                        """
                        DELETE FROM sessions
                        WHERE provider = ? AND session_id = ?
                        """,
                        (provider, session_id),
                    )
                elif (
                    kind == "session"
                    and provider
                    and session_id
                    and turn_key
                ):
                    connection.execute(
                        """
                        DELETE FROM events
                        WHERE provider = ? AND session_id = ? AND turn_key = ?
                        """,
                        (provider, session_id, turn_key),
                    )
                    connection.execute(
                        """
                        DELETE FROM turns
                        WHERE provider = ? AND session_id = ? AND turn_key = ?
                        """,
                        (provider, session_id, turn_key),
                    )
                return False
            connection.execute(
                """
                INSERT INTO documents(
                    document_id, kind, path, provider, session_id, turn_key,
                    workspace, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    kind = excluded.kind,
                    path = excluded.path,
                    provider = excluded.provider,
                    session_id = excluded.session_id,
                    turn_key = excluded.turn_key,
                    workspace = excluded.workspace,
                    metadata_json = excluded.metadata_json
                """,
                (
                    document_id,
                    kind,
                    str(path.resolve()),
                    provider,
                    session_id,
                    turn_key,
                    workspace,
                    utc_now(),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            self._mark_dirty(connection)
            if kind == "session" and provider and session_id and turn_key:
                connection.execute(
                    """
                    UPDATE turns SET document_id = ?
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (document_id, provider, session_id, turn_key),
                )
            return True

    def recent_documents(self, cwd: str, limit: int = 4) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT * FROM documents
                    WHERE (
                        workspace = ?
                        OR (kind = 'memory' AND COALESCE(workspace, '') = '')
                    )
                      AND kind IN ('session', 'handoff', 'memory')
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (cwd, limit),
                ).fetchall()
            )

    def document_for_path(self, path: Path) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM documents WHERE path = ?", (str(path.resolve()),)
            ).fetchone()

    def document(self, document_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()

    def documents_for_session(
        self,
        session_id: str,
        provider: str | None = None,
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if provider:
                return list(
                    connection.execute(
                        """
                        SELECT * FROM documents
                        WHERE provider = ? AND session_id = ?
                        """,
                        (provider, session_id),
                    ).fetchall()
                )
            return list(
                connection.execute(
                    "SELECT * FROM documents WHERE session_id = ?", (session_id,)
                ).fetchall()
            )

    def providers_for_session(self, session_id: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT provider FROM sessions WHERE session_id = ?
                UNION
                SELECT provider FROM documents
                WHERE session_id = ? AND provider IS NOT NULL
                ORDER BY provider
                """,
                (session_id, session_id),
            ).fetchall()
            providers = {str(row["provider"]) for row in rows}
            tombstones = connection.execute(
                """
                SELECT receipt_json FROM tombstones
                WHERE selector LIKE 'session:%'
                """
            ).fetchall()
            for row in tombstones:
                try:
                    receipt = json.loads(row["receipt_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if (
                    receipt.get("session_id") == session_id
                    and receipt.get("provider")
                ):
                    providers.add(str(receipt["provider"]))
            return sorted(providers)

    def tombstone_receipt(self, selector: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT receipt_json FROM tombstones WHERE selector = ?",
                (selector,),
            ).fetchone()
            return json.loads(row["receipt_json"]) if row else None

    def forget_document(self, document_id: str, reason: str) -> dict[str, Any]:
        selector = f"document:{document_id}"
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT receipt_json FROM tombstones WHERE selector = ?", (selector,)
            ).fetchone()
            if existing:
                return json.loads(existing["receipt_json"])
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            receipt = {
                "selector": selector,
                "found": bool(row),
                "paths": [row["path"]] if row else [],
                "kind": str(row["kind"]) if row else None,
                "provider": str(row["provider"]) if row and row["provider"] else None,
                "session_id": (
                    str(row["session_id"]) if row and row["session_id"] else None
                ),
                "turn_key": str(row["turn_key"]) if row and row["turn_key"] else None,
                "workspace": (
                    str(row["workspace"]) if row and row["workspace"] else None
                ),
                "deleted_at": utc_now(),
            }
            if row and row["kind"] == "session":
                turn = connection.execute(
                    """
                    SELECT * FROM turns
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (row["provider"], row["session_id"], row["turn_key"]),
                ).fetchone()
                source_receipt = {
                    "source_document": document_id,
                    "provider": row["provider"],
                    "session_id": row["session_id"],
                    "turn_key": row["turn_key"],
                }
                self._insert_tombstone(
                    connection,
                    (
                        f"source-turn:{row['provider']}:{row['session_id']}:"
                        f"{row['turn_key']}"
                    ),
                    reason,
                    source_receipt,
                )
                if turn and turn["prompt_hash"]:
                    self._insert_tombstone(
                        connection,
                        (
                            f"source-prompt:{row['provider']}:{row['session_id']}:"
                            f"{turn['prompt_hash']}"
                        ),
                        reason,
                        source_receipt,
                    )
                if turn and turn["response"]:
                    self._insert_tombstone(
                        connection,
                        (
                            f"source-response:{row['provider']}:{row['session_id']}:"
                            f"{stable_hash(str(turn['response']))}"
                        ),
                        reason,
                        source_receipt,
                    )
                connection.execute(
                    """
                    DELETE FROM events
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (row["provider"], row["session_id"], row["turn_key"]),
                )
                connection.execute(
                    """
                    DELETE FROM turns
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (row["provider"], row["session_id"], row["turn_key"]),
                )
            elif row and row["kind"] == "handoff":
                candidate_outbox_rows = connection.execute(
                    """
                    SELECT * FROM handoff_outbox
                    WHERE document_id = ?
                       OR (
                           provider = ? AND session_id = ? AND workspace = ?
                       )
                    """,
                    (
                        document_id,
                        row["provider"],
                        row["session_id"],
                        row["workspace"],
                    ),
                ).fetchall()
                outbox_rows = [
                    outbox
                    for outbox in candidate_outbox_rows
                    if outbox["document_id"] == document_id
                    or handoff_document_id(
                        str(outbox["provider"]),
                        str(outbox["session_id"]),
                        str(outbox["workspace"]),
                        str(outbox["summary"]),
                    )
                    == document_id
                ]
                for outbox in outbox_rows:
                    event_key = str(outbox["event_key"])
                    self._insert_tombstone(
                        connection,
                        f"source-handoff:{event_key}",
                        reason,
                        {
                            "source_document": document_id,
                            "provider": row["provider"],
                            "session_id": row["session_id"],
                        },
                    )
                    connection.execute(
                        "DELETE FROM events WHERE event_key = ?",
                        (event_key,),
                    )
            connection.execute(
                "DELETE FROM documents WHERE document_id = ?", (document_id,)
            )
            connection.execute(
                "UPDATE turns SET document_id = NULL WHERE document_id = ?", (document_id,)
            )
            self._insert_tombstone(
                connection,
                selector,
                reason,
                receipt,
            )
            self._mark_dirty(connection)
            return receipt

    def forget_session(
        self,
        session_id: str,
        reason: str,
        provider: str | None = None,
    ) -> dict[str, Any]:
        if provider is None:
            providers = self.providers_for_session(session_id)
            if len(providers) != 1:
                detail = (
                    "provider is required"
                    if not providers
                    else f"session ID is ambiguous across: {', '.join(providers)}"
                )
                raise ValueError(detail)
            provider = providers[0]
        selector = f"session:{provider}:{session_id}"
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT receipt_json FROM tombstones WHERE selector = ?", (selector,)
            ).fetchone()
            prior = json.loads(existing["receipt_json"]) if existing else {}
            rows = connection.execute(
                """
                SELECT path FROM documents
                WHERE provider = ? AND session_id = ?
                """,
                (provider, session_id),
            ).fetchall()
            paths = list(
                dict.fromkeys(
                    [
                        *[str(value) for value in prior.get("paths", [])],
                        *[str(row["path"]) for row in rows],
                    ]
                )
            )
            connection.execute(
                """
                DELETE FROM documents
                WHERE provider = ? AND session_id = ?
                """,
                (provider, session_id),
            )
            connection.execute(
                """
                DELETE FROM sessions
                WHERE provider = ? AND session_id = ?
                """,
                (provider, session_id),
            )
            receipt = {
                "selector": selector,
                "provider": provider,
                "session_id": session_id,
                "found": bool(rows) or bool(prior.get("found")),
                "paths": paths,
                "deleted_at": prior.get("deleted_at") or utc_now(),
            }
            connection.execute(
                """
                INSERT INTO tombstones(
                    tombstone_id, selector, reason, created_at, receipt_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(selector) DO UPDATE SET
                    receipt_json = excluded.receipt_json
                """,
                (
                    f"forget-{stable_hash(selector)[:20]}",
                    selector,
                    reason,
                    utc_now(),
                    json.dumps(receipt, ensure_ascii=False),
                ),
            )
            self._mark_dirty(connection)
            return receipt

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            result: dict[str, int] = {}
            for table in (
                "sessions",
                "turns",
                "events",
                "handoff_outbox",
                "promotion_outbox",
                "documents",
                "tombstones",
            ):
                result[table] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
            return result

    def document_count(self) -> int:
        with self.connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            )

    def checkpoint(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def index_dirty(self) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'index_dirty'"
            ).fetchone()
            return bool(row and row["value"] == "1")

    def index_generation(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'index_generation'"
            ).fetchone()
            return int(row["value"]) if row else 0

    def mark_index_clean(self, expected_generation: int | None = None) -> bool:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'index_generation'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            expected = (
                current if expected_generation is None else expected_generation
            )
            if current != expected:
                return False
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('index_dirty', '0')"
            )
            return True

    def mark_index_dirty(self) -> None:
        with self.transaction() as connection:
            self._mark_dirty(connection)

    def session_is_forgotten(self, provider: str, session_id: str) -> bool:
        with self.connect() as connection:
            return self._session_has_tombstone(
                connection,
                provider,
                session_id,
            )

    def expired_documents(
        self, kind: str, before: str, limit: int = 1_000
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT documents.* FROM documents
                    WHERE documents.kind = ? AND documents.created_at < ?
                      AND (
                          documents.kind != 'session'
                          OR NOT EXISTS (
                              SELECT 1 FROM promotion_outbox
                              WHERE promotion_outbox.provider = documents.provider
                                AND promotion_outbox.session_id = documents.session_id
                                AND promotion_outbox.turn_key = documents.turn_key
                          )
                      )
                    ORDER BY documents.created_at ASC LIMIT ?
                    """,
                    (kind, before, limit),
                ).fetchall()
            )

    def expired_raw_evidence_counts(self, before: str) -> dict[str, int]:
        with self.connect() as connection:
            pending_turns = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM turns
                    WHERE document_id IS NULL AND created_at < ?
                      AND NOT EXISTS (
                          SELECT 1 FROM promotion_outbox
                          WHERE promotion_outbox.provider = turns.provider
                            AND promotion_outbox.session_id = turns.session_id
                            AND promotion_outbox.turn_key = turns.turn_key
                      )
                    """,
                    (before,),
                ).fetchone()[0]
            )
            pending_handoffs = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM handoff_outbox
                    WHERE document_id IS NULL AND created_at < ?
                    """,
                    (before,),
                ).fetchone()[0]
            )
            orphan_events = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE created_at < ?
                      AND NOT EXISTS (
                          SELECT 1 FROM turns
                          WHERE turns.provider = events.provider
                            AND turns.session_id = events.session_id
                            AND events.turn_key IS NOT NULL
                            AND turns.turn_key = events.turn_key
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM handoff_outbox
                          WHERE handoff_outbox.event_key = events.event_key
                      )
                    """,
                    (before,),
                ).fetchone()[0]
            )
            return {
                "pending_turns": pending_turns,
                "pending_handoffs": pending_handoffs,
                "orphan_events": orphan_events,
            }

    def prune_expired_raw_evidence(
        self,
        before: str,
        reason: str = "retention",
    ) -> dict[str, int]:
        deleted = {
            "pending_turns": 0,
            "pending_handoffs": 0,
            "orphan_events": 0,
        }
        with self.transaction() as connection:
            turns = connection.execute(
                """
                SELECT * FROM turns
                WHERE document_id IS NULL AND created_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM promotion_outbox
                      WHERE promotion_outbox.provider = turns.provider
                        AND promotion_outbox.session_id = turns.session_id
                        AND promotion_outbox.turn_key = turns.turn_key
                  )
                """,
                (before,),
            ).fetchall()
            for turn in turns:
                receipt = {
                    "provider": turn["provider"],
                    "session_id": turn["session_id"],
                    "turn_key": turn["turn_key"],
                    "retained_content": False,
                }
                self._insert_tombstone(
                    connection,
                    (
                        f"source-turn:{turn['provider']}:{turn['session_id']}:"
                        f"{turn['turn_key']}"
                    ),
                    reason,
                    receipt,
                )
                if turn["prompt_hash"]:
                    self._insert_tombstone(
                        connection,
                        (
                            f"source-prompt:{turn['provider']}:{turn['session_id']}:"
                            f"{turn['prompt_hash']}"
                        ),
                        reason,
                        receipt,
                    )
                if turn["response"]:
                    self._insert_tombstone(
                        connection,
                        (
                            f"source-response:{turn['provider']}:{turn['session_id']}:"
                            f"{stable_hash(str(turn['response']))}"
                        ),
                        reason,
                        receipt,
                    )
                connection.execute(
                    """
                    DELETE FROM events
                    WHERE provider = ? AND session_id = ? AND turn_key = ?
                    """,
                    (turn["provider"], turn["session_id"], turn["turn_key"]),
                )
                connection.execute(
                    "DELETE FROM turns WHERE id = ?",
                    (turn["id"],),
                )
                deleted["pending_turns"] += 1

            handoffs = connection.execute(
                """
                SELECT * FROM handoff_outbox
                WHERE document_id IS NULL AND created_at < ?
                """,
                (before,),
            ).fetchall()
            for handoff in handoffs:
                self._insert_tombstone(
                    connection,
                    f"source-handoff:{handoff['event_key']}",
                    reason,
                    {
                        "provider": handoff["provider"],
                        "session_id": handoff["session_id"],
                        "retained_content": False,
                    },
                )
                connection.execute(
                    "DELETE FROM events WHERE event_key = ?",
                    (handoff["event_key"],),
                )
                deleted["pending_handoffs"] += 1

            events = connection.execute(
                """
                SELECT * FROM events
                WHERE created_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM turns
                      WHERE turns.provider = events.provider
                        AND turns.session_id = events.session_id
                        AND events.turn_key IS NOT NULL
                        AND turns.turn_key = events.turn_key
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM handoff_outbox
                      WHERE handoff_outbox.event_key = events.event_key
                  )
                """,
                (before,),
            ).fetchall()
            for event in events:
                self._insert_tombstone(
                    connection,
                    f"source-event:{event['event_key']}",
                    reason,
                    {
                        "provider": event["provider"],
                        "session_id": event["session_id"],
                        "event": event["name"],
                        "retained_content": False,
                    },
                )
                connection.execute(
                    "DELETE FROM events WHERE event_key = ?",
                    (event["event_key"],),
                )
                deleted["orphan_events"] += 1

            connection.execute(
                """
                DELETE FROM sessions
                WHERE NOT EXISTS (
                    SELECT 1 FROM turns
                    WHERE turns.provider = sessions.provider
                      AND turns.session_id = sessions.session_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM events
                    WHERE events.provider = sessions.provider
                      AND events.session_id = sessions.session_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM documents
                    WHERE documents.provider = sessions.provider
                      AND documents.session_id = sessions.session_id
                )
                """
            )
        return deleted
