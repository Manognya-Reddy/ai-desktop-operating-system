import threading
import time
from app.config import settings
from app.database.db import SessionLocal
from app.services.snapshots.snapshot_service import create_snapshot

_last_saved_path = None
_running = False


def set_active_path(path):
    global _last_saved_path
    _last_saved_path = path


def loop():
    global _running
    _running = True
    while _running:
        time.sleep(settings.SNAPSHOT_INTERVAL_SECONDS)
        if not _last_saved_path:
            continue
        db = SessionLocal()
        try:
            create_snapshot(db, _last_saved_path, trigger="periodic")
        except Exception:
            pass
        finally:
            db.close()


def start_background_checkpoints():
    t = threading.Thread(target=loop, daemon=True)
    t.start()


def stop_background_checkpoints():
    global _running
    _running = False
