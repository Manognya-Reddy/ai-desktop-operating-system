import os
import shutil
import subprocess
import tempfile
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "true"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test_pdf_features.db")

import numpy as np
import app.services.retrieval.embeddings as emb_mod
from app.database.db import init_db, SessionLocal, engine, Base
from app.services.snapshots.snapshot_service import create_snapshot, get_or_create_project
from app.services.chat.chat_service import classify, handle_message
from app.services.memory import timeline_service, mentor_service
from app.services.code import code_search


def deterministic_hash(word):
    total = 0
    for ch in word:
        total = total * 31 + ord(ch)
    return total


def fake_embed(text):
    words = text.lower().replace(",", " ").split()
    vec = np.zeros(512, dtype=np.float32)
    for w in words:
        vec[deterministic_hash(w) % 512] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


@pytest.fixture(autouse=True)
def patch_embeddings(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SIGNAL_SEMANTIC", True)
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
    d = tempfile.mkdtemp(prefix="pcm_pdf_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_git_repo(path, message="init"):
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True)


# --- timeline ---

def test_timeline_classify_routes_correctly():
    assert classify("what did I work on Tuesday") == "timeline"
    assert classify("what happened yesterday") == "timeline"


def test_timeline_reconstructs_day(db, project_dir):
    from datetime import datetime, timezone, timedelta
    from app.services.memory.event_service import log_event

    project = get_or_create_project(db, project_dir)
    e1 = log_event(db, project.id, "file_modified", "file", path="/x/graph.py", title="graph.py")
    e1.created_at = datetime.now(timezone.utc) - timedelta(days=3)
    e2 = log_event(db, project.id, "git_commit", "git", title="Added graph storage")
    e2.created_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()

    target_day = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%A").lower()
    events, start = timeline_service.build_timeline(db, f"what did i work on {target_day}")
    reply = timeline_service.format_timeline_reply(events, start)
    assert "graph.py" in reply
    assert "Added graph storage" in reply


def test_timeline_empty_day_says_nothing_recorded(db):
    events, start = timeline_service.build_timeline(db, "what did i work on monday")
    reply = timeline_service.format_timeline_reply(events, start)
    assert "nothing recorded" in reply.lower()


# --- code search ---

def test_code_search_classify_routes_correctly():
    assert classify("find the code responsible for sending email notifications") == "code_search"
    assert classify("which function handles login") == "code_search"


def test_code_symbol_extraction_finds_functions_and_classes(project_dir):
    path = os.path.join(project_dir, "notificationService.py")
    with open(path, "w") as f:
        f.write("def sendEmail(user):\n    pass\n\nclass NotificationQueue:\n    pass\n")
    symbols = code_search.extract_symbols(path)
    names = [s[1] for s in symbols]
    assert "sendEmail" in names
    assert "NotificationQueue" in names


def test_code_search_finds_indexed_function(db, project_dir):
    with open(os.path.join(project_dir, "notificationService.py"), "w") as f:
        f.write("def sendEmail(user, message):\n    pass\n")
    create_snapshot(db, project_dir)
    hits = code_search.search_code(db, "sendEmail function")
    assert len(hits) > 0
    assert any("sendEmail" in item.locator for item, score in hits)


def test_code_search_reply_formats_as_tree(db, project_dir):
    with open(os.path.join(project_dir, "notificationService.py"), "w") as f:
        f.write("def sendEmail(user):\n    pass\n")
    create_snapshot(db, project_dir)
    result = handle_message(db, "find the code responsible for sending email")
    assert "sendEmail" in result.reply


# --- dashboard ---

def test_dashboard_classify_routes_correctly():
    assert classify("show me the project health dashboard") == "dashboard"


def test_dashboard_counts_real_todos_and_uncommitted(db, project_dir):
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("# TODO: refactor\ndef foo():\n    pass\n# TODO: add tests\n")
    make_git_repo(project_dir)
    with open(os.path.join(project_dir, "new_file.py"), "w") as f:
        f.write("x = 1\n")

    snapshot = create_snapshot(db, project_dir)
    project = get_or_create_project(db, project_dir)
    report = dashboard_service_module().build_dashboard(db, project, snapshot)
    assert "Open TODOs             2" in report
    assert "Uncommitted changes    1" in report


def test_dashboard_never_fabricates_test_or_doc_numbers(db, project_dir):
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("x = 1\n")
    snapshot = create_snapshot(db, project_dir)
    project = get_or_create_project(db, project_dir)
    report = dashboard_service_module().build_dashboard(db, project, snapshot)
    assert "not available" in report.lower()


def dashboard_service_module():
    from app.services.memory import dashboard_service
    return dashboard_service


# --- mentor ---

def test_mentor_flags_auth_change_without_tests(db, project_dir):
    with open(os.path.join(project_dir, "authController.py"), "w") as f:
        f.write("def login():\n    pass\n")
    result = handle_message(db, f"save {project_dir}")
    assert "authentication" in result.reply.lower()


def test_mentor_flags_carried_over_uncommitted_changes(db, project_dir):
    make_git_repo(project_dir)
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\n")
    make_git_repo(project_dir, "init")
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")

    handle_message(db, f"save {project_dir}")
    second = handle_message(db, f"save {project_dir}")
    assert "carried over" in second.reply.lower()


def test_mentor_says_nothing_when_all_clear(db, project_dir):
    with open(os.path.join(project_dir, "notes.txt"), "w") as f:
        f.write("just notes\n")
    notes = mentor_service.build_mentor_notes(
        type("P", (), {"path": project_dir})(),
        type("S", (), {"files": [], "git_context": None})(),
        None,
    )
    assert notes == []


# --- safety layer: confirm-before-restore ---

def test_resume_asks_before_restoring_working_tree(db, project_dir):
    make_git_repo(project_dir)
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\n")
    make_git_repo(project_dir, "init")
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")

    handle_message(db, f"save {project_dir}")
    subprocess.run(["git", "checkout", "--", "app.py"], cwd=project_dir, capture_output=True)

    result = handle_message(db, f"resume {os.path.basename(project_dir)}")
    assert result.awaiting == "confirm_action"
    assert "ACTION REQUIRED" in result.reply
    with open(os.path.join(project_dir, "app.py")) as f:
        assert f.read() == "print(1)\n"


def test_resume_confirmation_yes_applies_the_restore(db, project_dir):
    make_git_repo(project_dir)
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\n")
    make_git_repo(project_dir, "init")
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")

    handle_message(db, f"save {project_dir}")
    subprocess.run(["git", "checkout", "--", "app.py"], cwd=project_dir, capture_output=True)

    prompt = handle_message(db, f"resume {os.path.basename(project_dir)}")
    confirmed = handle_message(db, "yes", awaiting=prompt.awaiting, context=prompt.data)
    with open(os.path.join(project_dir, "app.py")) as f:
        assert f.read() == "print(1)\nprint(2)\n"


def test_resume_confirmation_no_leaves_it_alone(db, project_dir):
    make_git_repo(project_dir)
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\n")
    make_git_repo(project_dir, "init")
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")

    handle_message(db, f"save {project_dir}")
    subprocess.run(["git", "checkout", "--", "app.py"], cwd=project_dir, capture_output=True)

    prompt = handle_message(db, f"resume {os.path.basename(project_dir)}")
    declined = handle_message(db, "no", awaiting=prompt.awaiting, context=prompt.data)
    with open(os.path.join(project_dir, "app.py")) as f:
        assert f.read() == "print(1)\n"
