import os
import json
import secrets
from datetime import datetime, timezone

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


class UsersCollection:
    """Minimal Mongo-collection-like wrapper (find_one/insert_one) backed by SQLite."""

    async def find_one(self, filter: dict) -> dict | None:
        email = filter.get("email")
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT name, email, hashed_password FROM users WHERE email = ?", (email,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def insert_one(self, document: dict) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO users (name, email, hashed_password) VALUES (?, ?, ?)",
                (document["name"], document["email"], document["hashed_password"]),
            )
            await db.commit()


users_collection = UsersCollection()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing',
                error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                section_key TEXT NOT NULL,
                question TEXT NOT NULL,
                hints TEXT NOT NULL,
                sentences TEXT NOT NULL,
                answer_key TEXT NOT NULL
            )
            """
        )
        await db.commit()


# --- Sessions -----------------------------------------------------------

async def create_session(user_email: str) -> str:
    token = secrets.token_urlsafe(32)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sessions (token, user_email, created_at) VALUES (?, ?, ?)",
            (token, user_email, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    return token


async def get_user_by_session(token: str) -> str | None:
    if not token:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_email FROM sessions WHERE token = ?", (token,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def delete_session(token: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await db.commit()


# --- Documents ------------------------------------------------------------

async def create_document(user_email: str, filename: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO documents (user_email, filename, status, created_at) VALUES (?, ?, 'processing', ?)",
            (user_email, filename, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def set_document_status(document_id: int, status: str, error: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE documents SET status = ?, error = ? WHERE id = ?",
            (status, error, document_id),
        )
        await db.commit()


SEED_OWNER = "__seed__"  # owner used for example documents visible to every user


async def get_document(document_id: int, user_email: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, filename, status, error, created_at FROM documents "
            "WHERE id = ? AND (user_email = ? OR user_email = ?)",
            (document_id, user_email, SEED_OWNER),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_documents(user_email: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, filename, status, error, created_at FROM documents "
            "WHERE user_email = ? OR user_email = ? ORDER BY created_at DESC",
            (user_email, SEED_OWNER),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def seed_document_exists(filename: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM documents WHERE user_email = ? AND filename = ?",
            (SEED_OWNER, filename),
        )
        return await cursor.fetchone() is not None


# --- Questions --------------------------------------------------------------

async def insert_questions(document_id: int, qa_data: dict) -> None:
    """qa_data shape: {section_key: {question, hint1..5, sentence1..5, answer_key}}"""
    async with aiosqlite.connect(DB_PATH) as db:
        for section_key, content in qa_data.items():
            hints = [content.get(f"hint{i}") for i in range(1, 6) if content.get(f"hint{i}")]
            sentences = [content.get(f"sentence{i}", "") for i in range(1, 6)]
            await db.execute(
                "INSERT INTO questions (document_id, section_key, question, hints, sentences, answer_key) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    section_key,
                    content.get("question", "No question provided"),
                    json.dumps(hints),
                    json.dumps(sentences),
                    content.get("answer_key", "No answer key provided"),
                ),
            )
        await db.commit()


async def get_questions_for_document(document_id: int) -> dict:
    """Returns {section_key: {question, hints, answer_key, full_answer}} for quiz endpoints."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT section_key, question, hints, sentences, answer_key FROM questions WHERE document_id = ?",
            (document_id,),
        )
        rows = await cursor.fetchall()

    questions = {}
    for row in rows:
        sentences = json.loads(row["sentences"])
        questions[row["section_key"]] = {
            "question": row["question"],
            "hints": json.loads(row["hints"]),
            "answer_key": row["answer_key"],
            "full_answer": " ".join(sentences).strip(),
        }
    return questions
