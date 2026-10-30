"""Vespera · db.py — SQLite persistence layer.

Replaces the in-memory dicts in main.py with a durable SQLite store.
Database file is controlled by the `db_path` environment variable
(default: vespera.db in the working directory).
"""

import os
import sqlite3
from typing import Optional

DB_PATH = os.getenv("db_path", "vespera.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = _conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                email         TEXT PRIMARY KEY,
                id            TEXT NOT NULL,
                name          TEXT NOT NULL,
                surname       TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token   TEXT PRIMARY KEY,
                email   TEXT NOT NULL,
                expires TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chats (
                id         TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                title      TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   TEXT    NOT NULL,
                role      TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                timestamp TEXT    NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS documents (
                id         TEXT    PRIMARY KEY,
                user_email TEXT    NOT NULL,
                filename   TEXT    NOT NULL,
                size       INTEGER NOT NULL,
                chunks     INTEGER NOT NULL,
                status     TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            );
        """)
    finally:
        conn.close()


# ── Users ──────────────────────────────────────────────

def user_create(user: dict) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO users (email, id, name, surname, password_hash, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user["email"], user["id"], user["name"], user["surname"],
             user["password_hash"], user["created_at"]),
        )
        conn.commit()
    finally:
        conn.close()


def user_get(email: str) -> Optional[dict]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def user_exists(email: str) -> bool:
    conn = _conn()
    try:
        return conn.execute(
            "SELECT 1 FROM users WHERE email=?", (email,)
        ).fetchone() is not None
    finally:
        conn.close()


def user_count() -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


# ── Sessions ───────────────────────────────────────────

def session_create(token: str, email: str, expires: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token, email, expires) VALUES (?,?,?)",
            (token, email, expires),
        )
        conn.commit()
    finally:
        conn.close()


def session_get(token: str) -> Optional[dict]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token=?", (token,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def session_delete(token: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
    finally:
        conn.close()


# ── Chats ──────────────────────────────────────────────

def chat_create(chat_id: str, user_email: str, title: str, created_at: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO chats (id, user_email, title, created_at) VALUES (?,?,?,?)",
            (chat_id, user_email, title, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def chat_upsert(chat_id: str, user_email: str, title: str, created_at: str) -> None:
    """Create chat if it does not already exist (INSERT OR IGNORE)."""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO chats (id, user_email, title, created_at) VALUES (?,?,?,?)",
            (chat_id, user_email, title, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def chat_get(chat_id: str) -> Optional[dict]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not row:
            return None
        chat = dict(row)
        msgs = conn.execute(
            "SELECT role, content, timestamp FROM messages WHERE chat_id=? ORDER BY id",
            (chat_id,),
        ).fetchall()
        chat["messages"] = [dict(m) for m in msgs]
        return chat
    finally:
        conn.close()


def chat_list(user_email: str) -> list:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at FROM chats "
            "WHERE user_email=? ORDER BY created_at DESC",
            (user_email,),
        ).fetchall()
        result = []
        for row in rows:
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=?", (row["id"],)
            ).fetchone()[0]
            result.append({
                "id":            row["id"],
                "title":         row["title"],
                "created_at":    row["created_at"],
                "message_count": count,
            })
        return result
    finally:
        conn.close()


def chat_delete(chat_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        conn.commit()
    finally:
        conn.close()


def chat_count() -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
    finally:
        conn.close()


def message_append(chat_id: str, role: str, content: str, timestamp: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content, timestamp) VALUES (?,?,?,?)",
            (chat_id, role, content, timestamp),
        )
        conn.commit()
    finally:
        conn.close()


# ── Documents ──────────────────────────────────────────

def doc_create(doc: dict) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO documents (id, user_email, filename, size, chunks, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (doc["id"], doc["user_email"], doc["filename"], doc["size"],
             doc["chunks"], doc["status"], doc["created_at"]),
        )
        conn.commit()
    finally:
        conn.close()


def doc_get(doc_id: str) -> Optional[dict]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def doc_list(user_email: str) -> list:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM documents WHERE user_email=? ORDER BY created_at DESC",
            (user_email,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def doc_delete(doc_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def doc_count() -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()
