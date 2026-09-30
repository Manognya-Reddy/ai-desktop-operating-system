import httpx
from app.config import settings
from app.services.chat import llm_intent
from app.services.chat.chat_service import handle_message
from app.database.db import init_db, SessionLocal, engine, Base


class FakeLLMResponse:
    def __init__(self, label, status_code=200):
        self.label = label
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)

    def json(self):
        return {"content": [{"text": self.label}]}


def test_returns_none_when_llm_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-key")
    assert llm_intent.classify_with_llm("save my project") is None


def test_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    assert llm_intent.classify_with_llm("save my project") is None


def test_returns_label_when_llm_enabled_and_call_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeLLMResponse("save"))
    assert llm_intent.classify_with_llm("please remember what I'm doing") == "save"


def test_rejects_label_outside_known_set(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeLLMResponse("banana"))
    assert llm_intent.classify_with_llm("hello") is None


def test_falls_back_gracefully_on_network_error(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-key")

    def raise_error(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", raise_error)
    assert llm_intent.classify_with_llm("save my project") is None


def test_chat_pipeline_still_works_with_llm_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    result = handle_message(db, "what projects do I have")
    assert "saved" in result.reply.lower() or "don't have" in result.reply.lower()
    db.close()


def test_chat_pipeline_uses_llm_label_when_available(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeLLMResponse("list"))

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    result = handle_message(db, "yo what have I got saved")
    assert "saved" in result.reply.lower() or "don't have" in result.reply.lower()
    db.close()
