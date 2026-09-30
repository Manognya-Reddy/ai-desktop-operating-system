import os
import re
import json
from datetime import datetime, timezone, timedelta

from app.models.project import Event, Project
from app.services.retrieval.embeddings import embed_text, embedding_to_str, str_to_embedding, cosine_similarity
from app.config import settings

DEDUP_MINUTES = 5

SECRET_PATTERN = re.compile(
    r"(password|passwd|pwd|api[_-]?key|secret|token|access[_-]?key)(\s*[:=]\s*)(\S+)",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"(bearer\s+)(\S+)", re.IGNORECASE)


def redact_secrets(text):
    text = SECRET_PATTERN.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    text = BEARER_PATTERN.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text


def already_logged_recently(db, project_id, event_type, dedup_key):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUP_MINUTES)
    existing = (
        db.query(Event)
        .filter(Event.project_id == project_id)
        .filter(Event.event_type == event_type)
        .filter((Event.path == dedup_key) | (Event.title == dedup_key))
        .filter(Event.created_at >= cutoff)
        .first()
    )
    return existing is not None


def log_event(db, project_id, event_type, source, path=None, title=None, description=None, meta=None, important=False):
    dedup_key = path if path is not None else title
    if dedup_key is not None and already_logged_recently(db, project_id, event_type, dedup_key):
        return None

    event = Event(
        project_id=project_id,
        event_type=event_type,
        source=source,
        path=path,
        title=title,
        description=description,
        meta=json.dumps(meta) if meta else None,
        important=important,
    )
    db.add(event)
    db.flush()

    if settings.SIGNAL_SEMANTIC:
        text = " ".join(filter(None, [event_type, title, description, path]))
        vec = embed_text(text)
        event.embedding = embedding_to_str(vec)

    db.commit()
    return event


FILE_TYPE_HINTS = {
    ".png": "image picture photo screenshot png",
    ".jpg": "image picture photo screenshot jpg jpeg",
    ".jpeg": "image picture photo screenshot jpg jpeg",
    ".gif": "image picture animation gif",
    ".svg": "image picture vector svg",
    ".pdf": "document pdf file",
    ".docx": "document word file",
    ".doc": "document word file",
    ".xlsx": "spreadsheet excel file",
    ".pptx": "presentation slides powerpoint",
    ".mp4": "video movie recording",
    ".mp3": "audio music sound recording",
}


def file_type_hint(path):
    ext = os.path.splitext(path)[1].lower()
    return FILE_TYPE_HINTS.get(ext, "")


def diff_and_log_snapshot_events(db, project, snapshot, previous_snapshot):
    if previous_snapshot is None:
        log_event(db, project.id, "vscode_workspace_opened", "vscode", path=project.path, title=project.name)
        for f in snapshot.files:
            log_event(db, project.id, "file_modified", "file", path=f.path, title=os.path.basename(f.path), description=file_type_hint(f.path))
        if snapshot.git_context and snapshot.git_context.last_commit_hash:
            log_git_commit_event(db, project, snapshot.git_context)
        for tab in snapshot.browser_tabs:
            log_event(db, project.id, "browser_tab_opened", "chrome", path=tab.url, title=tab.title)
        if snapshot.terminal_context and snapshot.terminal_context.recent_commands:
            for cmd in snapshot.terminal_context.recent_commands.split("\n"):
                cmd = cmd.strip()
                if cmd:
                    safe_cmd = redact_secrets(cmd)
                    log_event(db, project.id, "terminal_command", "terminal", description=safe_cmd, title=safe_cmd)
        return

    old_paths = {f.path for f in previous_snapshot.files}
    new_paths = {f.path for f in snapshot.files}
    new_sizes = {f.path: f.size_bytes for f in snapshot.files}
    old_sizes = {f.path: f.size_bytes for f in previous_snapshot.files}

    created = new_paths - old_paths
    removed = old_paths - new_paths

    renamed_pairs = []
    for new_path in list(created):
        for old_path in list(removed):
            if old_sizes.get(old_path) is not None and old_sizes.get(old_path) == new_sizes.get(new_path):
                renamed_pairs.append((old_path, new_path))
                created.discard(new_path)
                removed.discard(old_path)
                break

    for old_path, new_path in renamed_pairs:
        log_event(
            db, project.id, "file_renamed", "file", path=new_path,
            title=os.path.basename(new_path),
            description=f"renamed from {old_path} {file_type_hint(new_path)}".strip(),
            meta={"old_path": old_path, "new_path": new_path},
        )

    for path in created:
        log_event(db, project.id, "file_created", "file", path=path, title=os.path.basename(path), description=file_type_hint(path))

    for path in removed:
        log_event(db, project.id, "file_deleted", "file", path=path, title=os.path.basename(path), description=file_type_hint(path))

    still_present = new_paths & old_paths
    for path in still_present:
        log_event(db, project.id, "file_modified", "file", path=path, title=os.path.basename(path), description=file_type_hint(path))

    old_branch = previous_snapshot.git_context.branch if previous_snapshot.git_context else None
    new_branch = snapshot.git_context.branch if snapshot.git_context else None
    if new_branch and new_branch != old_branch:
        log_event(
            db, project.id, "git_branch_changed", "git", title=new_branch,
            description=f"switched from {old_branch} to {new_branch}" if old_branch else f"on branch {new_branch}",
        )

    old_commit = previous_snapshot.git_context.last_commit_hash if previous_snapshot.git_context else None
    new_commit = snapshot.git_context.last_commit_hash if snapshot.git_context else None
    if new_commit and new_commit != old_commit:
        log_git_commit_event(db, project, snapshot.git_context)

    old_tabs = {t.url for t in previous_snapshot.browser_tabs}
    for tab in snapshot.browser_tabs:
        if tab.url not in old_tabs:
            log_event(db, project.id, "browser_tab_opened", "chrome", path=tab.url, title=tab.title)

    old_commands = set((previous_snapshot.terminal_context.recent_commands or "").split("\n"))
    if snapshot.terminal_context and snapshot.terminal_context.recent_commands:
        new_commands = snapshot.terminal_context.recent_commands.split("\n")
        for cmd in new_commands:
            cmd = cmd.strip()
            if cmd and cmd not in old_commands:
                safe_cmd = redact_secrets(cmd)
                log_event(db, project.id, "terminal_command", "terminal", description=safe_cmd, title=safe_cmd)


def log_git_commit_event(db, project, git_context):
    changed = [f for f in (git_context.modified_files or "").split("\n") if f]
    log_event(
        db, project.id, "git_commit", "git",
        title=git_context.last_commit_message,
        description=git_context.last_commit_message,
        meta={
            "commit_hash": git_context.last_commit_hash,
            "branch": git_context.branch,
            "changed_files": changed,
        },
        important=True,
    )


def log_project_event(db, project, event_type):
    log_event(db, project.id, event_type, "project", path=project.path, title=project.name, important=True)


TIME_PATTERNS = {
    "today": 1,
    "yesterday": 2,
    "this week": 7,
    "last week": 14,
    "recently": 3,
    "this morning": 1,
}


def parse_time_range(text):
    lowered = text.lower()
    for phrase, days_back in TIME_PATTERNS.items():
        if phrase in lowered:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days_back)
            if phrase == "yesterday":
                start = end - timedelta(days=2)
                end = end - timedelta(days=1)
            return start, end
    return None


def keyword_overlap(query, event):
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    text = " ".join(filter(None, [
        event.event_type.replace("_", " "),
        event.title, event.description, event.path,
    ]))
    text_tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def recency_score(event):
    age_hours = (datetime.now(timezone.utc) - event.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
    return max(0.0, 1.0 - age_hours / (24 * 14))


def search_events(db, query, current_project_id=None, time_range_text="", top_k=8):
    q = db.query(Event)

    time_range = parse_time_range(time_range_text or query)
    if time_range:
        start, end = time_range
        q = q.filter(Event.created_at >= start, Event.created_at <= end)

    events = q.all()
    if not events:
        return []

    query_vec = embed_text(query) if settings.SIGNAL_SEMANTIC else None

    scored = []
    for event in events:
        semantic = 0.0
        if query_vec is not None and event.embedding:
            semantic = cosine_similarity(query_vec, str_to_embedding(event.embedding))
        keyword = keyword_overlap(query, event)
        recency = recency_score(event)
        boost = 0.08 if current_project_id and event.project_id == current_project_id else 0.0
        importance = 0.05 if event.important else 0.0

        score = 0.35 * semantic + 0.45 * keyword + 0.1 * recency + boost + importance
        scored.append((event, score))

    scored.sort(key=lambda x: (x[1], x[0].created_at), reverse=True)
    return scored[:top_k]
