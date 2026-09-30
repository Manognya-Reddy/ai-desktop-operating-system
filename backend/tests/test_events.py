import os
import time
import json
import shutil
import tempfile
import subprocess
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "true"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test_events.db")

import numpy as np
import app.services.retrieval.embeddings as emb_mod
from app.database.db import init_db, SessionLocal, engine, Base
from app.models.project import Event, Project
from app.services.snapshots.snapshot_service import create_snapshot, get_or_create_project
from app.services.memory import event_service


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


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def project_dir():
    d = tempfile.mkdtemp(prefix="pcm_events_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_git_repo(path, message="initial commit"):
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True)


def test_event_creation_basic(db, project_dir):
    project = get_or_create_project(db, project_dir)
    event = event_service.log_event(db, project.id, "file_created", "file", path="/x/y.txt", title="y.txt")
    assert event is not None
    assert event.event_type == "file_created"
    stored = db.query(Event).filter(Event.id == event.id).first()
    assert stored is not None
    assert stored.project_id == project.id


def test_file_created_event_from_snapshot_diff(db, project_dir):
    with open(os.path.join(project_dir, "first.txt"), "w") as f:
        f.write("hello")
    snap1 = create_snapshot(db, project_dir)

    time.sleep(1)
    with open(os.path.join(project_dir, "second.txt"), "w") as f:
        f.write("world")
    snap2 = create_snapshot(db, project_dir)

    events = db.query(Event).filter(Event.event_type == "file_created").all()
    paths = [e.path for e in events]
    assert any("second.txt" in p for p in paths)


def test_file_rename_detected(db, project_dir):
    old_path = os.path.join(project_dir, "diagram.png")
    with open(old_path, "w") as f:
        f.write("x" * 500)
    create_snapshot(db, project_dir)

    time.sleep(1)
    new_path = os.path.join(project_dir, "architecture.png")
    os.rename(old_path, new_path)
    create_snapshot(db, project_dir)

    renamed = db.query(Event).filter(Event.event_type == "file_renamed").all()
    assert len(renamed) == 1
    assert renamed[0].path == new_path
    meta = json.loads(renamed[0].meta)
    assert meta["old_path"] == old_path


def test_git_commit_event(db, project_dir):
    with open(os.path.join(project_dir, "auth.py"), "w") as f:
        f.write("x")
    make_git_repo(project_dir, "Implement OAuth authentication")
    create_snapshot(db, project_dir)

    commits = db.query(Event).filter(Event.event_type == "git_commit").all()
    assert len(commits) == 1
    assert commits[0].title == "Implement OAuth authentication"
    assert commits[0].important is True


def test_git_branch_changed_event(db, project_dir):
    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    make_git_repo(project_dir)
    create_snapshot(db, project_dir)

    subprocess.run(["git", "checkout", "-b", "feature-x"], cwd=project_dir, capture_output=True)
    create_snapshot(db, project_dir)

    branch_events = db.query(Event).filter(Event.event_type == "git_branch_changed").all()
    assert len(branch_events) == 1
    assert branch_events[0].title == "feature-x"


def test_git_history_retrieval_by_message(db, project_dir):
    with open(os.path.join(project_dir, "img.py"), "w") as f:
        f.write("x")
    make_git_repo(project_dir, "add image processing pipeline")
    project = get_or_create_project(db, project_dir)
    create_snapshot(db, project_dir)

    hits = event_service.search_events(db, "image processing", top_k=3)
    assert len(hits) > 0
    assert hits[0][0].event_type == "git_commit"


def test_chrome_tab_opened_event(db, project_dir, monkeypatch):
    from dataclasses import dataclass
    from typing import List

    @dataclass
    class FakeTab:
        url: str
        title: str = ""

    @dataclass
    class FakeChrome:
        tabs: List
        available: bool = True
        status: str = "ok"
        reason: str = None

    monkeypatch.setattr(
        "app.services.snapshots.snapshot_service.collect_chrome_context",
        lambda: FakeChrome(tabs=[FakeTab(url="https://fastapi.tiangolo.com/", title="FastAPI docs")]),
    )

    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    create_snapshot(db, project_dir)

    tab_events = db.query(Event).filter(Event.event_type == "browser_tab_opened").all()
    assert len(tab_events) == 1
    assert tab_events[0].title == "FastAPI docs"


def test_vscode_workspace_opened_event(db, project_dir):
    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    project = get_or_create_project(db, project_dir)
    create_snapshot(db, project_dir)

    opened = db.query(Event).filter(Event.event_type == "vscode_workspace_opened").all()
    assert len(opened) == 1
    assert opened[0].path == project.path


def test_terminal_command_event(db, project_dir, monkeypatch):
    from dataclasses import dataclass
    from typing import List

    @dataclass
    class FakeTerminal:
        working_directory: str
        recent_commands: List[str]
        active_venv: str = None
        running_processes: List[str] = None

        def __post_init__(self):
            if self.running_processes is None:
                self.running_processes = []

    monkeypatch.setattr(
        "app.services.snapshots.snapshot_service.collect_terminal_context",
        lambda path: FakeTerminal(working_directory=project_dir, recent_commands=["pytest -q"]),
    )

    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    create_snapshot(db, project_dir)

    cmds = db.query(Event).filter(Event.event_type == "terminal_command").all()
    assert len(cmds) == 1
    assert cmds[0].description == "pytest -q"


def test_terminal_secret_redaction(db, project_dir, monkeypatch):
    from dataclasses import dataclass
    from typing import List

    @dataclass
    class FakeTerminal:
        working_directory: str
        recent_commands: List[str]
        active_venv: str = None
        running_processes: List[str] = None

        def __post_init__(self):
            if self.running_processes is None:
                self.running_processes = []

    monkeypatch.setattr(
        "app.services.snapshots.snapshot_service.collect_terminal_context",
        lambda path: FakeTerminal(working_directory=project_dir, recent_commands=["export API_KEY=sk-verysecret123"]),
    )

    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    create_snapshot(db, project_dir)

    cmds = db.query(Event).filter(Event.event_type == "terminal_command").all()
    assert len(cmds) == 1
    assert "sk-verysecret123" not in cmds[0].description
    assert "[REDACTED]" in cmds[0].description


def test_event_deduplication(db, project_dir):
    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    project = get_or_create_project(db, project_dir)
    event_service.log_event(db, project.id, "file_created", "file", path="/x/a.txt", title="a.txt")
    event_service.log_event(db, project.id, "file_created", "file", path="/x/a.txt", title="a.txt")
    event_service.log_event(db, project.id, "file_created", "file", path="/x/a.txt", title="a.txt")

    matching = db.query(Event).filter(Event.path == "/x/a.txt").all()
    assert len(matching) == 1


def test_project_association(db, project_dir):
    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    project = get_or_create_project(db, project_dir)
    create_snapshot(db, project_dir)

    events = db.query(Event).filter(Event.project_id == project.id).all()
    assert len(events) > 0
    for e in events:
        assert e.project_id == project.id


def test_cross_project_search_finds_other_project(db, project_dir):
    project_a_dir = project_dir
    os.makedirs(os.path.join(project_a_dir, "assets"))
    with open(os.path.join(project_a_dir, "assets", "diagram.png"), "w") as f:
        f.write("x" * 300)
    create_snapshot(db, project_a_dir)

    project_b_dir = tempfile.mkdtemp(prefix="pcm_events_projB_")
    with open(os.path.join(project_b_dir, "notes.txt"), "w") as f:
        f.write("unrelated")
    project_b = get_or_create_project(db, project_b_dir)
    create_snapshot(db, project_b_dir)

    hits = event_service.search_events(db, "diagram png", current_project_id=project_b.id, top_k=5)
    assert len(hits) > 0
    top_event = hits[0][0]
    assert "diagram.png" in top_event.path
    assert top_event.project_id != project_b.id
    shutil.rmtree(project_b_dir, ignore_errors=True)


def test_current_project_gets_ranking_boost_not_hard_filter(db, project_dir):
    project_a_dir = project_dir
    with open(os.path.join(project_a_dir, "shared_topic.txt"), "w") as f:
        f.write("x")
    project_a = get_or_create_project(db, project_a_dir)
    create_snapshot(db, project_a_dir)

    project_b_dir = tempfile.mkdtemp(prefix="pcm_events_projB2_")
    with open(os.path.join(project_b_dir, "shared_topic.txt"), "w") as f:
        f.write("x")
    project_b = get_or_create_project(db, project_b_dir)
    create_snapshot(db, project_b_dir)

    hits_from_b = event_service.search_events(db, "shared_topic", current_project_id=project_b.id, top_k=5)
    project_ids = [h[0].project_id for h in hits_from_b]
    assert project_a.id in project_ids
    assert hits_from_b[0][0].project_id == project_b.id
    shutil.rmtree(project_b_dir, ignore_errors=True)


def test_historical_search_by_filename(db, project_dir):
    os.makedirs(os.path.join(project_dir, "assets"))
    with open(os.path.join(project_dir, "assets", "diagram.png"), "w") as f:
        f.write("x" * 300)
    create_snapshot(db, project_dir)

    hits = event_service.search_events(db, "diagram.png", top_k=3)
    assert len(hits) > 0
    assert "diagram.png" in hits[0][0].path


def test_semantic_historical_search_without_exact_words(db, project_dir):
    with open(os.path.join(project_dir, "resume_microsoft.pdf"), "w") as f:
        f.write("x")
    create_snapshot(db, project_dir)

    hits = event_service.search_events(db, "resume microsoft file", top_k=3)
    assert len(hits) > 0


def test_recency_ranking_prefers_newer_event(db, project_dir):
    project = get_or_create_project(db, project_dir)
    old_event = event_service.log_event(db, project.id, "file_modified", "file", path="/x/old.txt", title="old.txt")
    old_event.created_at = old_event.created_at.replace(year=2020)
    db.commit()
    event_service.log_event(db, project.id, "file_modified", "file", path="/x/new.txt", title="new.txt")

    hits = event_service.search_events(db, "txt file", top_k=5)
    paths_in_order = [h[0].path for h in hits]
    assert paths_in_order.index("/x/new.txt") < paths_in_order.index("/x/old.txt")


def test_time_range_parsing_filters_events(db, project_dir):
    project = get_or_create_project(db, project_dir)
    old_event = event_service.log_event(db, project.id, "file_modified", "file", path="/x/ancient.txt", title="ancient.txt")
    from datetime import datetime, timezone, timedelta
    old_event.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    event_service.log_event(db, project.id, "file_modified", "file", path="/x/recent.txt", title="recent.txt")

    hits = event_service.search_events(db, "txt file", time_range_text="today", top_k=5)
    paths = [h[0].path for h in hits]
    assert "/x/recent.txt" in paths
    assert "/x/ancient.txt" not in paths


def test_memory_layer_important_flag_on_commits(db, project_dir):
    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    make_git_repo(project_dir, "meaningful commit")
    create_snapshot(db, project_dir)

    commit_event = db.query(Event).filter(Event.event_type == "git_commit").first()
    assert commit_event.important is True


def test_existing_snapshot_save_still_works(db, project_dir):
    with open(os.path.join(project_dir, "a.py"), "w") as f:
        f.write("x")
    snapshot = create_snapshot(db, project_dir)
    assert snapshot.id is not None
    assert len(snapshot.files) == 1
