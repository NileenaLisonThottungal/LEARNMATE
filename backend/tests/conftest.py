import importlib
import os
import sys
import types

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _fake_generate_qa_from_text(text: str) -> dict:
    return {
        "1. TEST SECTION": {
            "question": "What is this document about?",
            "hint1": "It's a test.",
            "sentence1": "This is a test sentence used for verification.",
            "answer_key": "This is a test sentence used for verification.",
        }
    }


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own throwaway SQLite file instead of touching backend/app.db."""
    import database

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    yield


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    A TestClient wired to main.app, with models/app.py's heavy ML import chain
    (torch/transformers/pke/summarizer/flashtext) replaced by a stub so these
    tests don't need a working PyTorch install to verify the API surface.
    """
    fake_app_module = types.ModuleType("app")
    fake_app_module.generate_qa_from_text = _fake_generate_qa_from_text
    monkeypatch.setitem(sys.modules, "app", fake_app_module)

    import main

    importlib.reload(main)
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path / "uploads"))

    from fastapi.testclient import TestClient

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def signed_up_user(client):
    email = "student@example.com"
    password = "correct horse battery staple"
    client.post("/signup", data={"name": "Student", "email": email, "password": password})
    return {"email": email, "password": password}


@pytest.fixture
def authed_client(client, signed_up_user):
    res = client.post("/login", data=signed_up_user)
    assert res.status_code == 200
    return client
