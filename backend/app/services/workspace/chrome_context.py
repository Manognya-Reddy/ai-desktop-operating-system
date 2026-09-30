from dataclasses import dataclass, field
from typing import List, Optional
import httpx

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}/json/list"
TIMEOUT_SECONDS = 2.0


@dataclass
class BrowserTabInfo:
    url: str
    title: str = ""


@dataclass
class ChromeSnapshot:
    tabs: List[BrowserTabInfo] = field(default_factory=list)
    available: bool = False
    status: str = "unavailable"
    reason: Optional[str] = None


def is_real_tab(entry):
    if entry.get("type") != "page":
        return False
    url = entry.get("url", "")
    if not url.startswith(("http://", "https://")):
        return False
    return True


def collect_chrome_context():
    try:
        resp = httpx.get(CDP_URL, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        entries = resp.json()
    except httpx.ConnectError:
        return ChromeSnapshot(status="unavailable", reason="connection refused")
    except httpx.TimeoutException:
        return ChromeSnapshot(status="unavailable", reason="timeout")
    except Exception as e:
        return ChromeSnapshot(status="unavailable", reason=str(e))

    tabs = []
    for entry in entries:
        if is_real_tab(entry):
            tabs.append(BrowserTabInfo(url=entry.get("url", ""), title=entry.get("title", "")))

    return ChromeSnapshot(tabs=tabs, available=True, status="ok", reason=None)
