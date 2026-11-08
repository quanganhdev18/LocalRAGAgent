"""SQLite metadata store (documents, chunks, embeddings, FTS5, OCR pages, feedback)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    ocr_policy TEXT NOT NULL DEFAULT 'ask',   -- 'ask' | 'always' | 'never'
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_time REAL NOT NULL,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    page_count INTEGER,
    warning TEXT,
    missing_since REAL,
    prev_status TEXT,             -- status before it went missing (restored on rename/return)
    ocr_todo TEXT,                -- JSON list of PDF pages that need OCR
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
-- OCR results are stored per page so a shutdown mid-way loses nothing
CREATE TABLE IF NOT EXISTS ocr_pages (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY (document_id, page_number)
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    email TEXT,
    wants_news INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    section_heading TEXT,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'text',      -- 'text' | 'ocr' | 'notes'
    ocr_confidence REAL,
    hidden INTEGER NOT NULL DEFAULT 0,        -- hidden PPTX slide
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector BLOB NOT NULL,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    folded_text, tokenize='unicode61 remove_diacritics 0'
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vocab USING fts5vocab(chunks_fts, 'row');
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """SQLite wrapper with one connection per thread (WAL mode)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.conn().executescript(SCHEMA)
        self._migrate()

    # Additive migration for databases created by v2 (never drops or rewrites data).
    _ADD_COLUMNS = {
        "documents": [("page_count", "INTEGER"), ("warning", "TEXT"), ("missing_since", "REAL"), ("ocr_todo", "TEXT"), ("prev_status", "TEXT")],
        "chunks": [("source", "TEXT NOT NULL DEFAULT 'text'"), ("ocr_confidence", "REAL"),
                   ("hidden", "INTEGER NOT NULL DEFAULT 0")],
        "folders": [("ocr_policy", "TEXT NOT NULL DEFAULT 'ask'")],
    }

    def _migrate(self) -> None:
        c = self.conn()
        for table, cols in self._ADD_COLUMNS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        c.commit()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    # --- settings ------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        c = self.conn()
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))
        c.commit()

    # --- folders -------------------------------------------------------
    def add_folder(self, path: str, ocr_policy: str = "ask") -> int:
        c = self.conn()
        c.execute(
            "INSERT OR IGNORE INTO folders(path, ocr_policy, added_at) VALUES (?,?,?)",
            (path, ocr_policy, time.time()),
        )
        c.commit()
        return c.execute("SELECT id FROM folders WHERE path=?", (path,)).fetchone()["id"]

    def list_folders(self):
        return self.conn().execute("SELECT * FROM folders ORDER BY id").fetchall()

    def remove_folder(self, folder_id: int) -> None:
        """Forget a folder and its index entries. Never touches files on disk."""
        c = self.conn()
        for r in c.execute("SELECT id FROM documents WHERE folder_id=?", (folder_id,)).fetchall():
            self.delete_document(r["id"])
        c.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        c.commit()

    # --- documents / chunks -------------------------------------------
    def delete_chunks(self, document_id: int) -> None:
        c = self.conn()
        ids = [r["id"] for r in c.execute("SELECT id FROM chunks WHERE document_id=?", (document_id,))]
        c.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        c.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))  # embeddings cascade

    def delete_document(self, document_id: int) -> None:
        self.delete_chunks(document_id)
        self.conn().execute("DELETE FROM documents WHERE id=?", (document_id,))
        self.conn().commit()

    def index_status(self) -> dict:
        c = self.conn()
        by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM documents GROUP BY status")}
        return {
            "documents": sum(by_status.values()),
            "by_status": by_status,
            "chunks": c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "embedded": c.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],
        }
