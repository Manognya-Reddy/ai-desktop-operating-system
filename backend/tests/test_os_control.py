import os
import shutil
import tempfile
import httpx
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "false"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test_oscontrol.db")

from app.config import settings
from app.database.db import init_db, SessionLocal, engine, Base
from app.services.chat.chat_service import classify, handle_message
from app.services.chat import llm_intent
from app.services.osassist import os_control


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.mark.parametrize("message,expected", [
    ("open notepad", "open"),
    ("close chrome", "close_app"),
    ("quit spotify", "close_app"),
    ("lock my screen", "lock_screen"),
    ("take a screenshot", "screenshot"),
    ("create a folder called stuff at C:\\temp\\stuff", "make_folder"),
    ("delete file C:\\temp\\junk.txt", "delete_path"),
    ("empty the recycle bin", "empty_trash"),
])
def test_classify_os_control_intents(message, expected):
    assert classify(message) == expected


def test_resume_phrasing_not_shadowed_by_open_catch():
    assert classify("open the workspace i was using last night") == "resume"
    assert classify("resume the project i was working on yesterday") == "resume"


def test_make_folder_creates_real_folder(db):
    base = tempfile.mkdtemp()
    target = os.path.join(base, "new_stuff")
    result = handle_message(db, f"create a folder called x at {target}")
    assert os.path.isdir(target)
    assert "Created" in result.reply
    shutil.rmtree(base, ignore_errors=True)


def test_delete_path_requires_confirmation(db):
    base = tempfile.mkdtemp()
    target = os.path.join(base, "junk.txt")
    with open(target, "w") as f:
        f.write("x")

    prompt = handle_message(db, f"delete file {target}")
    assert prompt.awaiting == "confirm_action"
    assert os.path.exists(target)

    declined = handle_message(db, "no", awaiting="confirm_action", context=prompt.data)
    assert os.path.exists(target)
    assert "not doing" in declined.reply.lower()

    prompt2 = handle_message(db, f"delete file {target}")
    confirmed = handle_message(db, "yes", awaiting="confirm_action", context=prompt2.data)
    assert not os.path.exists(target)
    shutil.rmtree(base, ignore_errors=True)


def test_close_app_requires_confirmation(db):
    prompt = handle_message(db, "close some_process_that_does_not_exist")
    assert prompt.awaiting == "confirm_action"
    assert prompt.data["action"] == "close_app"


def test_empty_trash_requires_confirmation(db):
    prompt = handle_message(db, "empty the recycle bin")
    assert prompt.awaiting == "confirm_action"
    assert prompt.data["action"] == "empty_trash"


def test_app_alias_resolves_known_name():
    assert os_control.resolve_app_target("notepad") == "notepad.exe"
    assert os_control.resolve_app_target("some_random_app") == "some_random_app"


def test_llm_entity_extraction_pulls_app_name_from_sentence(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"text": "spotify"}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
    result = llm_intent.extract_entity(
        "hey can you please close spotify for me, i dont need it open anymore",
        "application name",
    )
    assert result == "spotify"


def test_llm_entity_extraction_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    assert llm_intent.extract_entity("close spotify", "application name") is None


def test_delete_nonexistent_path_reports_error(db):
    result = handle_message(db, "delete file C:\\does\\not\\exist\\at\\all.txt")
    confirmed = handle_message(db, "yes", awaiting="confirm_action", context=result.data)
    assert "couldn't" in confirmed.reply.lower()
