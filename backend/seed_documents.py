import json
import os

from database import SEED_OWNER, create_document, insert_questions, seed_document_exists, set_document_status

SEED_FILES = {
    "Resources": "updated_final_t5_bert_hint_qa.json",
    "Agriculture": "agriculture.json",
    "Water Resources": "Water_resources.json",
}


async def seed_example_documents():
    """One-time migration of the original static JSON datasets into the
    documents/questions tables, so they still show up as example content
    for every user. Safe to call on every startup — skips files already seeded."""
    backend_dir = os.path.dirname(__file__)

    for display_name, json_filename in SEED_FILES.items():
        if await seed_document_exists(display_name):
            continue

        file_path = os.path.join(backend_dir, json_filename)
        if not os.path.exists(file_path):
            continue

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                qa_data = json.load(f)
        except Exception:
            continue

        document_id = await create_document(SEED_OWNER, display_name)
        await insert_questions(document_id, qa_data)
        await set_document_status(document_id, "ready")
