import os
import shutil
import tempfile
import subprocess
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "false"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test_restore.db")

from app.database.db import init_db, SessionLocal, engine, Base
from app.services.snapshots.snapshot_service import create_snapshot
from app.services.restoration.restoration_service import build_plan, execute_plan
from app.services.workspace.misinfo_check import check_url
from app.services.chat import access_control
from app.services.chat.chat_service import handle_message


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def git_project_dir():
    d = tempfile.mkdtemp(prefix="pcm_restore_")
    subprocess.run(["git", "init"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=d, capture_output=True)
    with open(os.path.join(d, "app.py"), "w") as f:
        f.write("print(1)\n")
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_git_diff_captured_on_save(db, git_project_dir):
    with open(os.path.join(git_project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")
    snap = create_snapshot(db, git_project_dir)
    assert snap.git_context.diff_patch is not None
    assert "print(2)" in snap.git_context.diff_patch


def test_untracked_file_content_captured_on_save(db, git_project_dir):
    with open(os.path.join(git_project_dir, "new_file.py"), "w") as f:
        f.write("x = 42\n")
    snap = create_snapshot(db, git_project_dir)
    assert snap.git_context.untracked_content is not None
    assert "x = 42" in snap.git_context.untracked_content


def test_working_tree_restored_on_resume(db, git_project_dir):
    with open(os.path.join(git_project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")
    with open(os.path.join(git_project_dir, "new_file.py"), "w") as f:
        f.write("x = 42\n")

    snap = create_snapshot(db, git_project_dir)

    subprocess.run(["git", "checkout", "--", "app.py"], cwd=git_project_dir, capture_output=True)
    os.remove(os.path.join(git_project_dir, "new_file.py"))

    plan = build_plan(git_project_dir, snap)
    executed, warnings, skipped = execute_plan(plan, confirm_unsafe=True)

    assert "git_working_tree" in executed
    with open(os.path.join(git_project_dir, "app.py")) as f:
        assert f.read() == "print(1)\nprint(2)\n"
    assert os.path.exists(os.path.join(git_project_dir, "new_file.py"))
    with open(os.path.join(git_project_dir, "new_file.py")) as f:
        assert f.read() == "x = 42\n"


def test_working_tree_restore_is_unsafe_without_confirmation(db, git_project_dir):
    with open(os.path.join(git_project_dir, "app.py"), "w") as f:
        f.write("print(1)\nprint(2)\n")
    snap = create_snapshot(db, git_project_dir)

    plan = build_plan(git_project_dir, snap)
    working_tree_item = next(i for i in plan if i["component"] == "git_working_tree")
    assert working_tree_item["safe"] is False

    subprocess.run(["git", "checkout", "--", "app.py"], cwd=git_project_dir, capture_output=True)
    executed, warnings, skipped = execute_plan(plan, confirm_unsafe=False)
    assert "git_working_tree" not in executed
    assert any(i["component"] == "git_working_tree" for i in skipped)


def test_misinfo_check_flags_known_domain():
    assert check_url("https://infowars.com/some-article") is not None
    assert check_url("https://github.com/torvalds/linux") is None


def test_access_control_gates_data_intents(db):
    access_control.set_pin(db, "4821")
    result = handle_message(db, "what projects do I have")
    assert result.awaiting == "enter_pin"


def test_access_control_wrong_pin_rejected(db):
    access_control.set_pin(db, "4821")
    locked = handle_message(db, "what projects do I have")
    result = handle_message(db, "0000", awaiting="enter_pin", context=locked.data)
    assert result.awaiting == "enter_pin"
    assert "didn't match" in result.reply.lower()


def test_access_control_correct_pin_unlocks(db):
    access_control.set_pin(db, "4821")
    locked = handle_message(db, "what projects do I have")
    result = handle_message(db, "4821", awaiting="enter_pin", context=locked.data)
    assert result.unlocked is True
    assert result.awaiting != "enter_pin"


def test_access_control_no_pin_set_never_gates(db):
    result = handle_message(db, "what projects do I have")
    assert result.awaiting != "enter_pin"


def test_save_intent_never_gated(db):
    access_control.set_pin(db, "4821")
    result = handle_message(db, "save this project")
    assert result.awaiting != "enter_pin"
