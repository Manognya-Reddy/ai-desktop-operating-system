import os
import shutil
import tempfile
import subprocess
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "true"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test_nlu.db")

import numpy as np
import app.services.retrieval.embeddings as emb_mod
from app.database.db import init_db, SessionLocal, engine, Base
from app.services.snapshots.snapshot_service import create_snapshot, get_or_create_project
from app.services.chat.chat_service import classify, handle_message


def deterministic_hash(word):
    total = 0
    for ch in word:
        total = total * 31 + ord(ch)
    return total


def fake_embed(text):
    words = text.lower().split()
    vec = np.zeros(512, dtype=np.float32)
    for w in words:
        vec[deterministic_hash(w) % 512] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


@pytest.fixture(autouse=True)
def patch_embeddings(monkeypatch):
    monkeypatch.setattr(emb_mod, "embed_text", fake_embed)
    monkeypatch.setattr("app.services.snapshots.snapshot_service.embed_text", fake_embed)
    monkeypatch.setattr("app.services.memory.memory_service.embed_text", fake_embed)
    monkeypatch.setattr("app.services.memory.event_service.embed_text", fake_embed)
    monkeypatch.setattr("app.services.retrieval.hybrid.embed_text", fake_embed)


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def project_dir():
    d = tempfile.mkdtemp(prefix="pcm_nlu_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.mark.parametrize("message", [
    "save",
    "Save what I'm working on right now.",
    "Remember this workspace.",
    "Save this project.",
    "take a snapshot of my current workspace",
    "Remember these tabs and files.",
])
def test_save_synonyms_map_to_save_intent(message):
    assert classify(message) == "save"


@pytest.mark.parametrize("message", [
    "resume myproject",
    "Bring back my project.",
    "Resume the project I was working on yesterday.",
    "Restore my authentication workspace.",
    "Open the workspace I was using last night.",
    "Take me back to the project where I was working on OAuth.",
    "Restore this project's previous context.",
])
def test_resume_synonyms_map_to_resume_intent(message):
    assert classify(message) == "resume"


@pytest.mark.parametrize("message", [
    "What was my last commit?",
    "What did I commit today?",
    "Which branch was I working on yesterday?",
    "What files were changed in my OAuth commit?",
])
def test_git_questions_map_to_recall_intent(message):
    assert classify(message) == "recall"


@pytest.mark.parametrize("message", [
    "Where is the PNG I added yesterday?",
    "Which files did I change when I implemented login?",
    "Where did I put that image?",
])
def test_file_questions_map_to_recall_intent(message):
    assert classify(message) == "recall"


@pytest.mark.parametrize("message", [
    "What GitHub repository was I working on?",
    "What documentation was I reading?",
    "What GitHub pages was I looking at?",
])
def test_browser_history_questions_map_to_recall_intent(message):
    assert classify(message) == "recall"


def test_check_chrome_still_works_as_shortcut():
    assert classify("check chrome") == "chrome_status"


def test_full_pipeline_save_via_natural_language(db, project_dir):
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("x")
    result = handle_message(db, f"Remember this workspace at {project_dir}")
    assert "Saved" in result.reply
    assert result.active_project_id is not None


def test_full_pipeline_resume_via_natural_language(db, project_dir):
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("x")
    save_result = handle_message(db, f"save {project_dir}")
    project_id = save_result.active_project_id

    resume_result = handle_message(db, "bring back my project", active_project_id=project_id)
    assert "esum" in resume_result.reply.lower() or "restor" in resume_result.reply.lower()


def test_full_pipeline_cross_project_history_question(db, project_dir):
    project_a_dir = project_dir
    os.makedirs(os.path.join(project_a_dir, "assets"))
    with open(os.path.join(project_a_dir, "assets", "diagram.png"), "w") as f:
        f.write("x" * 300)
    create_snapshot(db, project_a_dir)

    project_b_dir = tempfile.mkdtemp(prefix="pcm_nlu_projB_")
    with open(os.path.join(project_b_dir, "notes.txt"), "w") as f:
        f.write("y")
    project_b = create_snapshot(db, project_b_dir).project_id

    result = handle_message(db, "Where is the diagram png I added?", active_project_id=project_b)
    assert "diagram.png" in result.reply
    shutil.rmtree(project_b_dir, ignore_errors=True)


def test_full_pipeline_git_commit_question(db, project_dir):
    with open(os.path.join(project_dir, "auth.py"), "w") as f:
        f.write("x")
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Implement OAuth authentication"], cwd=project_dir, capture_output=True)
    create_snapshot(db, project_dir)

    result = handle_message(db, "What did I commit when I implemented OAuth?")
    assert "OAuth" in result.reply or "authentication" in result.reply.lower()
