import asyncio
import os
import sys
import uuid

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import EmailStr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import uvicorn

from database import (
    create_document,
    create_session,
    delete_session,
    get_document,
    get_questions_for_document,
    get_user_by_session,
    init_db,
    insert_questions,
    list_documents,
    set_document_status,
    users_collection,
)
from document_parser import extract_text
from seed_documents import seed_example_documents

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "models"))
from app import generate_qa_from_text  # noqa: E402  (models/app.py)

app = FastAPI()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


@app.on_event("startup")
async def on_startup():
    await init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    await seed_example_documents()


app.mount("/public", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page():
    file_path = os.path.join("..", "frontend", "login.html")
    return FileResponse(file_path, media_type="text/html")


@app.get("/signup")
async def signup_page():
    file_path = os.path.join("..", "frontend", "signup.html")
    return FileResponse(file_path, media_type="text/html")


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def get_current_user(session_token: str | None = Cookie(default=None)) -> str:
    user_email = await get_user_by_session(session_token)
    if not user_email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_email


@app.post("/signup")
async def signup(response: Response, name: str = Form(...), email: EmailStr = Form(...), password: str = Form(...)):
    existing_user = await users_collection.find_one({"email": email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = get_password_hash(password)
    user_data = {"name": name, "email": email, "hashed_password": hashed_password}
    await users_collection.insert_one(user_data)
    token = await create_session(str(email))
    response.set_cookie(key="session_token", value=token, httponly=True, samesite="lax")
    return {"msg": "User created successfully"}


@app.post("/login")
async def login(response: Response, email: EmailStr = Form(...), password: str = Form(...)):
    user = await users_collection.find_one({"email": email})
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    token = await create_session(str(email))
    response.set_cookie(key="session_token", value=token, httponly=True, samesite="lax")
    return {"msg": "Login successful"}


@app.post("/logout")
async def logout(response: Response, session_token: str | None = Cookie(default=None)):
    if session_token:
        await delete_session(session_token)
    response.delete_cookie("session_token")
    return {"msg": "Logged out"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    file_path = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(file_path, media_type="text/html")


# --- Per-user in-memory quiz state ------------------------------------------
# Keyed by user_email. Holds the currently selected document's questions and
# study/test progress. Not persisted across restarts by design (progress is
# session-scoped, not a durable record).
SESSION_STATE: dict[str, dict] = {}


def _get_state(user_email: str) -> dict:
    return SESSION_STATE.setdefault(
        user_email,
        {
            "document_id": None,
            "questions": {},
            "question_keys": [],
            "question_index": 0,
            "test_questions": [],
            "test_index": 0,
            "test_score": 0,
        },
    )


ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
PROCESSING_TIMEOUT_SECONDS = 600  # 10 minutes
MAX_CONCURRENT_PROCESSING_JOBS = 2
_processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROCESSING_JOBS)


def _sniff_content_matches_extension(ext: str, header: bytes) -> bool:
    """Cheap magic-byte check so a renamed .exe etc. can't reach the parser
    just because it has a .pdf/.docx extension."""
    if ext == ".pdf":
        return header.startswith(b"%PDF")
    if ext == ".docx":
        return header.startswith(b"PK\x03\x04")  # docx is a zip archive
    if ext == ".txt":
        return b"\x00" not in header  # reject binary data masquerading as text
    return False


async def process_document_job(document_id: int, file_path: str):
    async with _processing_semaphore:
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_run_pipeline, file_path), timeout=PROCESSING_TIMEOUT_SECONDS
            )
            if not text:
                raise ValueError("No questions could be generated from this document.")
            await insert_questions(document_id, text)
            await set_document_status(document_id, "ready")
        except asyncio.TimeoutError:
            await set_document_status(document_id, "failed", "Processing timed out")
        except Exception as e:
            await set_document_status(document_id, "failed", str(e))
        finally:
            try:
                os.remove(file_path)
            except OSError:
                pass


def _run_pipeline(file_path: str) -> dict:
    text = extract_text(file_path)
    return generate_qa_from_text(text)


@app.post("/api/documents")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    user_email: str = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20MB)")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if not _sniff_content_matches_extension(ext, content[:8]):
        raise HTTPException(status_code=400, detail="File content doesn't match its extension")

    document_id = await create_document(user_email, file.filename)
    stored_path = os.path.join(UPLOAD_DIR, f"{document_id}_{uuid.uuid4().hex}{ext}")
    with open(stored_path, "wb") as f:
        f.write(content)

    background_tasks.add_task(process_document_job, document_id, stored_path)
    return {"document_id": document_id, "status": "processing"}


@app.get("/api/documents")
async def get_documents(user_email: str = Depends(get_current_user)):
    return await list_documents(user_email)


@app.get("/api/documents/{document_id}/status")
async def document_status(document_id: int, user_email: str = Depends(get_current_user)):
    document = await get_document(document_id, user_email)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.post("/api/select_document")
async def select_document(document_id: int = Form(...), user_email: str = Depends(get_current_user)):
    document = await get_document(document_id, user_email)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document["status"] != "ready":
        raise HTTPException(status_code=400, detail=f"Document is not ready (status: {document['status']})")

    questions = await get_questions_for_document(document_id)
    state = _get_state(user_email)
    state["document_id"] = document_id
    state["questions"] = questions
    state["question_keys"] = list(questions.keys())
    state["question_index"] = 0
    state["test_questions"] = []
    state["test_index"] = 0
    state["test_score"] = 0
    return {"msg": f"Document '{document['filename']}' loaded successfully", "total_questions": len(questions)}


MIN_ANSWER_WORDS = 4  # answers shorter than this can't be a genuine response
MIN_OVERLAP_RATIO = 0.15  # guards against a couple of stuffed keywords scoring as "correct"


def compute_similarity(user_answer: str, correct_answer: str, require_overlap: bool = True) -> float:
    if len(user_answer.split()) < MIN_ANSWER_WORDS:
        return 0.0

    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform([user_answer, correct_answer])
    similarity = cosine_similarity(vectors[0], vectors[1])[0][0] * 100

    if require_overlap:
        user_words = {w.lower() for w in user_answer.split() if w.isalpha()}
        correct_words = {w.lower() for w in correct_answer.split() if w.isalpha()}
        if correct_words and len(user_words & correct_words) / len(correct_words) < MIN_OVERLAP_RATIO:
            similarity = min(similarity, 40.0)

    return round(similarity, 2)


@app.get("/api/question", response_class=JSONResponse)
async def get_question(user_email: str = Depends(get_current_user)):
    state = _get_state(user_email)
    if state["question_index"] >= len(state["question_keys"]):
        raise HTTPException(status_code=404, detail="No more questions available")
    current_key = state["question_keys"][state["question_index"]]
    q_data = state["questions"][current_key]
    state["question_index"] += 1
    return {"question_id": current_key, "question": q_data["question"]}


@app.post("/api/answer", response_class=JSONResponse)
async def evaluate_answer(
    question_id: str = Form(...), user_answer: str = Form(...), user_email: str = Depends(get_current_user)
):
    state = _get_state(user_email)
    if question_id not in state["questions"]:
        raise HTTPException(status_code=404, detail="Question not found")
    q_data = state["questions"][question_id]
    correct_answer = q_data["full_answer"]
    similarity_score = compute_similarity(user_answer, correct_answer)
    hints_str = "\n".join(q_data["hints"]) if q_data["hints"] else ""

    if similarity_score >= 90:
        return {"similarity_score": similarity_score, "result": "✅ You are correct!"}
    elif similarity_score >= 50:
        return {
            "similarity_score": similarity_score,
            "result": "🤔 Not quite right, try again!",
            "hints": hints_str,
            "correct_answer": q_data["answer_key"],
        }
    else:
        return {
            "similarity_score": similarity_score,
            "result": "❌ Incorrect.",
            "hints": hints_str,
            "correct_answer": q_data["answer_key"],
        }


@app.post("/api/test/start", response_class=JSONResponse)
async def start_test(user_email: str = Depends(get_current_user)):
    state = _get_state(user_email)
    state["test_index"] = 0
    state["test_score"] = 0
    state["test_questions"] = [
        {
            "question_id": section,
            "question": content["question"],
            "hints": content["hints"],
            "answer_key": content["answer_key"],
            "full_answer": content["full_answer"],
        }
        for section, content in state["questions"].items()
    ]
    return {"msg": "Test started", "total_questions": len(state["test_questions"])}


@app.get("/api/test/question", response_class=JSONResponse)
async def get_test_question(user_email: str = Depends(get_current_user)):
    state = _get_state(user_email)
    if state["test_index"] < len(state["test_questions"]):
        return state["test_questions"][state["test_index"]]
    return {
        "msg": "Test Completed",
        "score": state["test_score"],
        "max_score": len(state["test_questions"]) * 5,
    }


@app.post("/api/test/answer", response_class=JSONResponse)
async def evaluate_test_answer(
    question_id: str = Form(...), user_answer: str = Form(...), user_email: str = Depends(get_current_user)
):
    state = _get_state(user_email)
    if state["test_index"] >= len(state["test_questions"]):
        raise HTTPException(status_code=400, detail="Test already completed")

    current_q = state["test_questions"][state["test_index"]]
    if current_q["question_id"] != question_id:
        raise HTTPException(status_code=400, detail="Invalid question id")

    correct_answer = current_q["full_answer"]
    similarity_score = compute_similarity(user_answer, correct_answer)

    marks = 0
    if similarity_score >= 90:
        result = "✅ Correct!"
        marks = 5
    elif similarity_score >= 50:
        result = "🤔 Partially correct!"
        marks = sum(
            1 for hint in current_q["hints"] if compute_similarity(user_answer, hint, require_overlap=False) >= 50
        )
    else:
        result = "❌ Incorrect!"

    state["test_score"] += marks
    state["test_index"] += 1

    if state["test_index"] < len(state["test_questions"]):
        return {
            "result": result,
            "marks_awarded": marks,
            "current_score": state["test_score"],
            "next_question": state["test_questions"][state["test_index"]],
        }
    return {
        "result": result,
        "marks_awarded": marks,
        "current_score": state["test_score"],
        "msg": "Test Completed",
        "max_score": len(state["test_questions"]) * 5,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
