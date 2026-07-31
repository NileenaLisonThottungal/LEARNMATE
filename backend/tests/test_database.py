import pytest

import database


@pytest.mark.asyncio
async def test_session_round_trip():
    await database.init_db()
    token = await database.create_session("user@example.com")
    assert await database.get_user_by_session(token) == "user@example.com"

    await database.delete_session(token)
    assert await database.get_user_by_session(token) is None


@pytest.mark.asyncio
async def test_get_user_by_session_rejects_missing_or_empty_token():
    await database.init_db()
    assert await database.get_user_by_session(None) is None
    assert await database.get_user_by_session("") is None
    assert await database.get_user_by_session("not-a-real-token") is None


@pytest.mark.asyncio
async def test_document_ownership_is_scoped_per_user():
    await database.init_db()
    doc_id = await database.create_document("owner@example.com", "notes.txt")

    assert await database.get_document(doc_id, "owner@example.com") is not None
    assert await database.get_document(doc_id, "someone-else@example.com") is None

    owner_docs = await database.list_documents("owner@example.com")
    assert len(owner_docs) == 1
    assert await database.list_documents("someone-else@example.com") == []


@pytest.mark.asyncio
async def test_seed_owned_documents_are_visible_to_every_user():
    await database.init_db()
    seed_doc_id = await database.create_document(database.SEED_OWNER, "Example Textbook")
    await database.set_document_status(seed_doc_id, "ready")

    assert await database.get_document(seed_doc_id, "anyone@example.com") is not None
    docs = await database.list_documents("anyone@example.com")
    assert any(d["filename"] == "Example Textbook" for d in docs)


@pytest.mark.asyncio
async def test_document_status_lifecycle():
    await database.init_db()
    doc_id = await database.create_document("owner@example.com", "notes.pdf")
    doc = await database.get_document(doc_id, "owner@example.com")
    assert doc["status"] == "processing"
    assert doc["error"] is None

    await database.set_document_status(doc_id, "failed", "boom")
    doc = await database.get_document(doc_id, "owner@example.com")
    assert doc["status"] == "failed"
    assert doc["error"] == "boom"


@pytest.mark.asyncio
async def test_insert_and_retrieve_questions_reconstructs_full_answer():
    await database.init_db()
    doc_id = await database.create_document("owner@example.com", "notes.txt")

    qa_data = {
        "1. INTRO": {
            "question": "What is X?",
            "hint1": "First hint",
            "sentence1": "X is the first thing.",
            "hint2": "Second hint",
            "sentence2": "X is also the second thing.",
            "answer_key": "X is the first thing. X is also the second thing.",
        }
    }
    await database.insert_questions(doc_id, qa_data)

    questions = await database.get_questions_for_document(doc_id)
    assert list(questions.keys()) == ["1. INTRO"]
    entry = questions["1. INTRO"]
    assert entry["question"] == "What is X?"
    assert entry["hints"] == ["First hint", "Second hint"]
    assert entry["full_answer"] == "X is the first thing. X is also the second thing."


@pytest.mark.asyncio
async def test_seed_document_exists_is_idempotency_check():
    await database.init_db()
    assert await database.seed_document_exists("Resources") is False
    doc_id = await database.create_document(database.SEED_OWNER, "Resources")
    await database.set_document_status(doc_id, "ready")
    assert await database.seed_document_exists("Resources") is True
