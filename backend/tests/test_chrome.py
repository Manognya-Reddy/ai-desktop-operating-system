import os
import tempfile
import pytest

os.environ["PCM_SIGNAL_SEMANTIC"] = "false"
os.environ["PCM_DB_PATH"] = os.path.join(tempfile.gettempdir(), "pcm_test_chrome.db")

import httpx
from app.services.workspace import chrome_context


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)

    def json(self):
        return self._payload


def test_collects_normal_page_tabs(monkeypatch):
    payload = [
        {"type": "page", "title": "Wikipedia", "url": "https://www.wikipedia.org/"},
        {"type": "page", "title": "GitHub", "url": "https://github.com/"},
    ]
    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse(payload))
    snap = chrome_context.collect_chrome_context()
    assert snap.status == "ok"
    assert len(snap.tabs) == 2
    assert snap.tabs[0].title == "Wikipedia"
    assert snap.tabs[0].url == "https://www.wikipedia.org/"


def test_filters_out_browser_ui(monkeypatch):
    payload = [
        {"type": "page", "title": "Wikipedia", "url": "https://www.wikipedia.org/"},
        {"type": "browser_ui", "title": "Omnibox Popup", "url": ""},
    ]
    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse(payload))
    snap = chrome_context.collect_chrome_context()
    assert len(snap.tabs) == 1
    assert snap.tabs[0].title == "Wikipedia"


def test_filters_out_iframe(monkeypatch):
    payload = [
        {"type": "page", "title": "GitHub", "url": "https://github.com/"},
        {"type": "iframe", "title": "embedded", "url": "https://embedded.example/"},
    ]
    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse(payload))
    snap = chrome_context.collect_chrome_context()
    assert len(snap.tabs) == 1
    assert snap.tabs[0].title == "GitHub"


def test_filters_out_chrome_internal_urls(monkeypatch):
    payload = [
        {"type": "page", "title": "New Tab", "url": "chrome://newtab/"},
        {"type": "page", "title": "Extensions", "url": "chrome-untrusted://extensions/"},
        {"type": "page", "title": "FastAPI", "url": "https://fastapi.tiangolo.com/"},
    ]
    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse(payload))
    snap = chrome_context.collect_chrome_context()
    assert len(snap.tabs) == 1
    assert snap.tabs[0].title == "FastAPI"


def test_endpoint_unavailable_reports_status_not_empty_list(monkeypatch):
    def raise_connect_error(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", raise_connect_error)
    snap = chrome_context.collect_chrome_context()
    assert snap.status == "unavailable"
    assert snap.available is False
    assert snap.reason == "connection refused"
    assert snap.tabs == []


def test_endpoint_timeout_reports_status(monkeypatch):
    def raise_timeout(url, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "get", raise_timeout)
    snap = chrome_context.collect_chrome_context()
    assert snap.status == "unavailable"
    assert snap.reason == "timeout"


def test_uses_127_0_0_1_and_json_list_endpoint():
    assert chrome_context.CDP_URL == "http://127.0.0.1:9222/json/list"


def test_resume_restores_exactly_the_saved_urls(monkeypatch):
    from app.database.db import init_db, SessionLocal, engine, Base
    from app.services.snapshots.snapshot_service import create_snapshot
    from app.services.restoration.restoration_service import build_plan, execute_plan

    payload = [
        {"type": "page", "title": "Wikipedia", "url": "https://www.wikipedia.org/"},
        {"type": "page", "title": "GitHub", "url": "https://github.com/"},
        {"type": "page", "title": "unrelated", "url": "https://unrelated.example/"},
    ]
    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse(payload))

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    project_dir = tempfile.mkdtemp(prefix="pcm_chrome_resume_")
    with open(os.path.join(project_dir, "main.py"), "w") as f:
        f.write("print(1)")

    snapshot = create_snapshot(db, project_dir)

    from app.models.project import BrowserTab
    keep_urls = ["https://www.wikipedia.org/", "https://github.com/"]
    for tab in list(snapshot.browser_tabs):
        if tab.url not in keep_urls:
            db.delete(tab)
    db.commit()
    db.refresh(snapshot)

    opened = []
    def fake_open_tabs(urls):
        opened.extend(urls)
        return True, ""
    monkeypatch.setattr(
        "app.services.restoration.restoration_service._open_tabs", fake_open_tabs,
    )

    plan = build_plan(project_dir, snapshot)
    execute_plan(plan, confirm_unsafe=True)

    assert set(opened) == set(keep_urls)
    db.close()
