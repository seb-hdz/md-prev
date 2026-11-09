"""
notes_manager.py
----------------
Backend persistence layer for the notes/annotation feature.
Uses SQLite3 for ACID-compliant storage in ~/Library/Application Support/MD-Prev/notes.sqlite3.

Thread-safety: each public method opens its own connection and uses short transactions.
"""

import sqlite3
import os
import uuid
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import paths_util

logger = logging.getLogger(__name__)

DB_FILENAME = 'notes.sqlite3'

_SCHEMA_VERSION = 1

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    document_key TEXT    NOT NULL,
    id           TEXT    NOT NULL,
    body         TEXT    NOT NULL DEFAULT '',
    selector     TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    PRIMARY KEY (document_key, id)
);

CREATE INDEX IF NOT EXISTS idx_notes_doc ON notes(document_key);
"""


class NotesManager:
    """Manages note persistence via SQLite.

    Each method that touches the DB opens and closes its own connection
    so that callers from any thread can use it without coordination.
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            support_dir = paths_util.get_app_support_path()
            db_path = os.path.join(support_dir, DB_FILENAME)
        self._db_path = db_path
        self._ensure_schema()
        logger.info(f'[notes_manager] DB path: {self._db_path}')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        try:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version < _SCHEMA_VERSION:
                conn.executescript(_CREATE_TABLE_SQL)
                conn.execute(f'PRAGMA user_version = {_SCHEMA_VERSION}')
                conn.commit()
                logger.info('[notes_manager] Schema initialized (v%d).', _SCHEMA_VERSION)
        finally:
            conn.close()

    @staticmethod
    def resolve_document_key(filepath: str) -> str:
        """Canonical key for a file: resolved absolute POSIX path."""
        return str(Path(filepath).resolve())

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec='seconds')

    @staticmethod
    def _generate_id() -> str:
        return f'note_{uuid.uuid4().hex[:12]}'

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d['selector'] = json.loads(d['selector'])
        return d

    # ------------------------------------------------------------------
    # Public API (called from previewer bridge)
    # ------------------------------------------------------------------

    def list_notes(self, filepath: str) -> list[dict]:
        """Return all notes for *filepath* as a list of dicts."""
        doc_key = self.resolve_document_key(filepath)
        conn = self._connect()
        try:
            rows = conn.execute(
                'SELECT * FROM notes WHERE document_key = ? ORDER BY created_at',
                (doc_key,)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def create_note(self, filepath: str, body: str, selector: dict,
                    note_id: str | None = None) -> dict:
        """Insert a new note.  Returns the created note dict.

        If *note_id* is supplied (for idempotent retries) and already exists
        with the same body and selector, the existing record is returned.
        """
        body = (body or '').strip()
        if not body:
            raise ValueError('Note body must not be blank.')
        self._validate_selector(selector)

        doc_key = self.resolve_document_key(filepath)
        nid = note_id or self._generate_id()
        now = self._now_iso()
        selector_json = json.dumps(selector, ensure_ascii=False)

        conn = self._connect()
        try:
            # Check for existing (idempotent retry)
            existing = conn.execute(
                'SELECT * FROM notes WHERE document_key = ? AND id = ?',
                (doc_key, nid)
            ).fetchone()
            if existing:
                ex = self._row_to_dict(existing)
                if ex['body'] == body and json.dumps(ex['selector'], ensure_ascii=False) == selector_json:
                    return ex
                raise ValueError(f'Note {nid} already exists with different content (conflict).')

            conn.execute(
                'INSERT INTO notes (document_key, id, body, selector, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (doc_key, nid, body, selector_json, now, now)
            )
            conn.commit()
            logger.info('[notes_manager] Created note %s for %s', nid, doc_key)
            return {
                'document_key': doc_key,
                'id': nid,
                'body': body,
                'selector': selector,
                'created_at': now,
                'updated_at': now,
            }
        finally:
            conn.close()

    def update_note(self, filepath: str, note_id: str, *,
                    body: str | None = None,
                    selector: dict | None = None) -> dict:
        """Update the body and/or selector of an existing note.

        Returns the updated note dict.
        """
        doc_key = self.resolve_document_key(filepath)

        sets = []
        params = []
        if body is not None:
            body = body.strip()
            if not body:
                raise ValueError('Note body must not be blank.')
            sets.append('body = ?')
            params.append(body)
        if selector is not None:
            self._validate_selector(selector)
            sets.append('selector = ?')
            params.append(json.dumps(selector, ensure_ascii=False))
        if not sets:
            raise ValueError('Nothing to update.')

        now = self._now_iso()
        sets.append('updated_at = ?')
        params.append(now)
        params.extend([doc_key, note_id])

        conn = self._connect()
        try:
            cur = conn.execute(
                f'UPDATE notes SET {", ".join(sets)} WHERE document_key = ? AND id = ?',
                params
            )
            if cur.rowcount == 0:
                raise KeyError(f'Note {note_id} not found for {doc_key}')
            conn.commit()

            row = conn.execute(
                'SELECT * FROM notes WHERE document_key = ? AND id = ?',
                (doc_key, note_id)
            ).fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    def delete_note(self, filepath: str, note_id: str) -> bool:
        """Delete a note.  Idempotent — returns True if it existed."""
        doc_key = self.resolve_document_key(filepath)
        conn = self._connect()
        try:
            cur = conn.execute(
                'DELETE FROM notes WHERE document_key = ? AND id = ?',
                (doc_key, note_id)
            )
            conn.commit()
            deleted = cur.rowcount > 0
            if deleted:
                logger.info('[notes_manager] Deleted note %s from %s', note_id, doc_key)
            return deleted
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_selector(sel: dict):
        if not isinstance(sel, dict):
            raise ValueError('selector must be a dict')
        if 'exact' not in sel or not sel['exact']:
            raise ValueError('selector.exact is required and must be non-empty')
        for key in ('prefix', 'suffix'):
            if key in sel and not isinstance(sel[key], str):
                raise ValueError(f'selector.{key} must be a string')
        for key in ('start', 'end'):
            if key in sel and not isinstance(sel[key], (int, float)):
                raise ValueError(f'selector.{key} must be a number')

