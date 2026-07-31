import io


def test_signup_then_duplicate_email_rejected(client):
    payload = {"name": "Student", "email": "dup@example.com", "password": "pw123456"}
    res = client.post("/signup", data=payload)
    assert res.status_code == 200

    res = client.post("/signup", data=payload)
    assert res.status_code == 400


def test_signup_logs_the_user_in_immediately(client):
    payload = {"name": "Student", "email": "fresh@example.com", "password": "pw123456"}
    res = client.post("/signup", data=payload)
    assert res.status_code == 200
    assert "session_token" in res.cookies

    res = client.get("/api/documents")
    assert res.status_code == 200


def test_login_sets_session_cookie_and_rejects_wrong_password(client, signed_up_user):
    res = client.post("/login", data=signed_up_user)
    assert res.status_code == 200
    assert "session_token" in res.cookies

    bad = dict(signed_up_user, password="wrong-password")
    res = client.post("/login", data=bad)
    assert res.status_code == 400


def test_logout_clears_session(authed_client):
    res = authed_client.post("/logout")
    assert res.status_code == 200
    # Session should no longer grant access to a protected endpoint.
    res = authed_client.get("/api/documents")
    assert res.status_code == 401


def test_protected_endpoint_requires_auth(client):
    res = client.get("/api/documents")
    assert res.status_code == 401


def test_seeded_documents_are_listed_and_ready(authed_client):
    res = authed_client.get("/api/documents")
    assert res.status_code == 200
    docs = res.json()
    filenames = {d["filename"] for d in docs}
    assert {"Resources", "Agriculture", "Water Resources"}.issubset(filenames)
    assert all(d["status"] == "ready" for d in docs)


def test_select_document_then_answer_flow(authed_client):
    docs = authed_client.get("/api/documents").json()
    resources_doc = next(d for d in docs if d["filename"] == "Resources")

    res = authed_client.post("/api/select_document", data={"document_id": resources_doc["id"]})
    assert res.status_code == 200
    assert res.json()["total_questions"] > 0

    res = authed_client.get("/api/question")
    assert res.status_code == 200
    question = res.json()
    assert "question_id" in question and "question" in question

    res = authed_client.post(
        "/api/answer",
        data={"question_id": question["question_id"], "user_answer": "an unrelated nonsense reply"},
    )
    assert res.status_code == 200
    assert "result" in res.json()


def test_select_nonexistent_document_returns_404(authed_client):
    res = authed_client.post("/api/select_document", data={"document_id": 999999})
    assert res.status_code == 404


def test_upload_rejects_unsupported_extension(authed_client):
    res = authed_client.post(
        "/api/documents",
        files={"file": ("malware.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
    )
    assert res.status_code == 400


def test_upload_rejects_oversized_file(authed_client):
    import main

    big_content = b"a" * (main.MAX_UPLOAD_BYTES + 1)
    res = authed_client.post(
        "/api/documents",
        files={"file": ("notes.txt", io.BytesIO(big_content), "text/plain")},
    )
    assert res.status_code == 413


def test_upload_rejects_content_extension_mismatch(authed_client):
    # A renamed executable claiming to be a PDF should be rejected by the magic-byte check.
    res = authed_client.post(
        "/api/documents",
        files={"file": ("fake.pdf", io.BytesIO(b"MZ\x90\x00fake-exe-content"), "application/pdf")},
    )
    assert res.status_code == 400


def test_upload_valid_txt_file_processes_successfully(authed_client):
    content = b"This is a perfectly valid plain text document for testing."
    res = authed_client.post(
        "/api/documents",
        files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
    )
    assert res.status_code == 200
    document_id = res.json()["document_id"]

    # TestClient runs BackgroundTasks synchronously, so processing (stubbed to be
    # instant in these tests) has already finished by the time we check status.
    res = authed_client.get(f"/api/documents/{document_id}/status")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"


def test_compute_similarity_edge_cases():
    from main import compute_similarity

    exact = compute_similarity("the quick brown fox jumps over", "the quick brown fox jumps over")
    assert exact >= 90

    unrelated = compute_similarity("bananas are yellow and tasty", "quantum mechanics is hard to learn")
    assert unrelated < 50


def test_compute_similarity_rejects_too_short_answers():
    from main import compute_similarity

    # A near-exact match that's too short to be a genuine answer should be capped at 0.
    assert compute_similarity("fox", "the quick brown fox jumps over the lazy dog") == 0.0


def test_compute_similarity_guards_against_keyword_stuffing():
    from main import compute_similarity

    correct_answer = (
        "Photosynthesis converts light energy into chemical energy stored in glucose "
        "using carbon dioxide and water inside the chloroplasts of plant cells."
    )
    # Long enough to pass the word-count floor, but shares almost no real words with
    # the correct answer -- should not score as a confident match.
    stuffed = "unrelated filler words padding this answer out to be long enough zzz zzz zzz zzz"
    score = compute_similarity(stuffed, correct_answer)
    assert score <= 40.0
