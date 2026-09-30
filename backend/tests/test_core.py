"""
Core tests (spec section 32). Run with: pytest -q
Uses a temp SQLite DB per test session and disables semantic embeddings
so tests run offline/CPU-only without downloading a model.
"""
import os
import tempfile
import shutil
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "false"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test.db")

from app.database.db import init_db, SessionLocal, engine, Base
from app.models.project import Project, Snapshot
from app.services.snapshots.snapshot_service import create_snapshot, get_or_create_project
from app.services.retrieval.keyword_search import keyword_score
from app.services.retrieval.hybrid import hybrid_search
from app.services.restoration.safety import classify_command, is_dangerous_command
from app.services.restoration.restoration_service import build_plan
from app.services.workspace.detection import score_project_membership
from app.services.workspace.filesystem import collect_filesystem_context, FilesystemSnapshot
from app.services.workspace.git_context import GitSnapshot
from app.services.workspace.terminal_context import TerminalSnapshot
from app.services.workspace.chrome_context import ChromeSnapshot


@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def demo_project_dir():
    tmp = tempfile.mkdtemp(prefix="pcm_demo_")
    with open(os.path.join(tmp, "main.py"), "w") as f:
        f.write("print('hello')")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_get_or_create_project_is_idempotent(db, demo_project_dir):
    p1 = get_or_create_project(db, demo_project_dir)
    p2 = get_or_create_project(db, demo_project_dir)
    assert p1.id == p2.id


def test_snapshot_creation_persists_files(db, demo_project_dir):
    snapshot = create_snapshot(db, demo_project_dir)
    assert snapshot.id is not None
    assert len(snapshot.files) >= 1
    assert snapshot.terminal_context is not None
    assert snapshot.git_context is not None


def test_filesystem_collector_ignores_missing_dir():
    result = collect_filesystem_context("/path/does/not/exist")
    assert result.recent_files == []


def test_keyword_score_matches_name():
    p = Project(name="AI Resume Screener", path="/x", semantic_description="BERT resume parser")
    assert keyword_score("resume screener", p) > 0
    assert keyword_score("totally unrelated topic", p) == 0


def test_hybrid_search_ranks_by_score(db, demo_project_dir):
    create_snapshot(db, demo_project_dir)
    results = hybrid_search(db, "main")
    assert len(results) == 1
    assert results[0].score >= 0


def test_dangerous_command_is_blocked():
    assert is_dangerous_command("rm -rf /")
    assert classify_command("rm -rf /") == "blocked"
    assert classify_command("python app.py") == "needs_confirmation"
    assert classify_command("cd /tmp") == "safe"


def test_restoration_plan_excludes_blocked_commands(db, demo_project_dir):
    snapshot = create_snapshot(db, demo_project_dir)
    plan = build_plan(demo_project_dir, snapshot)
    for item in plan:
        if item["component"] == "terminal_command":
            assert "rm -rf" not in item["action"]["command"].lower()


def test_project_detection_scores_matching_folder(demo_project_dir):
    fs = FilesystemSnapshot(project_path=demo_project_dir)
    result = score_project_membership(
        demo_project_dir, fs, GitSnapshot(), TerminalSnapshot(working_directory=demo_project_dir), ChromeSnapshot()
    )
    assert result.breakdown["folder_match"] == 1.0
    assert result.breakdown["terminal_directory_match"] == 1.0


def test_project_detection_scores_zero_for_unrelated_path(demo_project_dir):
    fs = FilesystemSnapshot(project_path=demo_project_dir)
    result = score_project_membership(
        "/completely/different/path", fs, GitSnapshot(), TerminalSnapshot(working_directory="/other"), ChromeSnapshot()
    )
    assert result.score < 0.5


def test_vscode_detection_picks_most_recently_touched(monkeypatch, tmp_path):
    import json
    import time
    import app.services.osassist.os_tools as ot

    fake_appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    ws_storage = fake_appdata / "Code" / "User" / "workspaceStorage"
    ws_storage.mkdir(parents=True)

    old_folder = tmp_path / "old_project"
    old_folder.mkdir()
    new_folder = tmp_path / "new_project"
    new_folder.mkdir()

    def make_entry(name, folder, age_seconds_ago):
        entry = ws_storage / name
        entry.mkdir()
        meta = entry / "workspace.json"
        meta.write_text(json.dumps({"folder": "file://" + str(folder)}))
        state = entry / "state.vscdb"
        state.write_text("x")
        touch_time = time.time() - age_seconds_ago
        os.utime(meta, (touch_time, touch_time))
        os.utime(state, (touch_time, touch_time))

    make_entry("hash_old", old_folder, 5000)
    make_entry("hash_new", new_folder, 5)

    result = ot.detect_recent_vscode_folder()
    assert result == str(new_folder)


def test_memory_indexing_and_recall(db, demo_project_dir, monkeypatch):
    import numpy as np
    import app.services.retrieval.embeddings as emb_mod

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

    monkeypatch.setattr(emb_mod, "embed_text", fake_embed)
    monkeypatch.setattr("app.services.snapshots.snapshot_service.embed_text", fake_embed)
    monkeypatch.setattr("app.services.memory.memory_service.embed_text", fake_embed)
    monkeypatch.setattr("app.services.memory.event_service.embed_text", fake_embed)
    monkeypatch.setenv("PCM_SIGNAL_SEMANTIC", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "SIGNAL_SEMANTIC", True)

    with open(os.path.join(demo_project_dir, "resume_for_microsoft.pdf"), "w") as f:
        f.write("x")

    snapshot = create_snapshot(db, demo_project_dir)

    from app.models.project import MemoryItem
    items = db.query(MemoryItem).filter(MemoryItem.snapshot_id == snapshot.id).all()
    assert len(items) >= 1

    from app.services.memory.memory_service import recall
    hits = recall(db, "resume for microsoft", top_k=3)
    assert len(hits) >= 1
