import hashlib
from app.models.project import AccessLock

GATED_KINDS = ("recall", "digest", "list", "files", "git", "resume", "find", "listdir")


def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


def is_configured(db):
    return db.query(AccessLock).first() is not None


def set_pin(db, pin):
    existing = db.query(AccessLock).first()
    if existing:
        existing.pin_hash = hash_pin(pin)
    else:
        db.add(AccessLock(pin_hash=hash_pin(pin)))
    db.commit()


def check_pin(db, pin):
    lock = db.query(AccessLock).first()
    if not lock:
        return True
    return lock.pin_hash == hash_pin(pin)


def is_gated(kind):
    return kind in GATED_KINDS
