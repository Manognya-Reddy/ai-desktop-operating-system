import os
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.project import (
    Project, Snapshot, SnapshotFile, BrowserTab, GitContext, TerminalContext
)
from app.services.workspace.filesystem import collect_filesystem_context
from app.services.workspace.git_context import collect_git_context
from app.services.workspace.chrome_context import collect_chrome_context
from app.services.workspace.terminal_context import collect_terminal_context
from app.services.workspace.misinfo_check import check_url
from app.services.retrieval.embeddings import embed_text, embedding_to_str
from app.config import settings


def build_semantic_description(name, git, recent_files):
    parts = [f"Project {name}."]
    if git.available and git.branch:
        parts.append(f"Git branch {git.branch}.")
    if recent_files:
        exts = {os.path.splitext(f.path)[1] for f in recent_files if os.path.splitext(f.path)[1]}
        if exts:
            parts.append("Recent file types: " + ", ".join(sorted(exts)) + ".")
    return " ".join(parts)


def get_or_create_project(db, project_path):
    project_path = os.path.normpath(project_path)
    project = db.query(Project).filter(Project.path == project_path).first()
    if project:
        return project
    name = os.path.basename(project_path.rstrip(os.sep)) or project_path
    project = Project(name=name, path=project_path)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def create_snapshot(db, project_path, trigger="manual"):
    project = get_or_create_project(db, project_path)

    previous_snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.project_id == project.id)
        .order_by(Snapshot.created_at.desc())
        .first()
    )

    fs = collect_filesystem_context(project.path) if settings.SIGNAL_FILES else None
    git = collect_git_context(project.path) if settings.SIGNAL_GIT else None
    chrome = collect_chrome_context() if settings.SIGNAL_BROWSER else None
    terminal = collect_terminal_context(project.path) if settings.SIGNAL_TERMINAL else None

    from app.services.workspace.filesystem import FilesystemSnapshot
    from app.services.workspace.git_context import GitSnapshot
    from app.services.workspace.chrome_context import ChromeSnapshot
    from app.services.workspace.terminal_context import TerminalSnapshot
    fs = fs or FilesystemSnapshot(project_path=project.path)
    git = git or GitSnapshot()
    chrome = chrome or ChromeSnapshot()
    terminal = terminal or TerminalSnapshot(working_directory=project.path)

    snapshot = Snapshot(project_id=project.id, trigger=trigger)
    db.add(snapshot)
    db.flush()

    for f in fs.recent_files:
        db.add(SnapshotFile(
            snapshot_id=snapshot.id, path=f.path, kind="recent",
            last_modified=datetime.fromtimestamp(f.last_modified, tz=timezone.utc),
            size_bytes=f.size,
        ))

    for t in chrome.tabs:
        warning = check_url(t.url, title=t.title)
        db.add(BrowserTab(snapshot_id=snapshot.id, url=t.url, title=t.title, warning=warning))

    db.add(GitContext(
        snapshot_id=snapshot.id,
        repository_path=git.repository_path,
        branch=git.branch,
        last_commit_hash=git.last_commit_hash,
        last_commit_message=git.last_commit_message,
        modified_files="\n".join(git.modified_files),
        untracked_files="\n".join(git.untracked_files),
        diff_patch=git.diff_patch,
        untracked_content=json.dumps(git.untracked_content) if git.untracked_content else None,
    ))

    db.add(TerminalContext(
        snapshot_id=snapshot.id,
        working_directory=terminal.working_directory,
        recent_commands="\n".join(terminal.recent_commands),
        active_venv=terminal.active_venv,
        running_processes="\n".join(terminal.running_processes),
    ))

    description = build_semantic_description(project.name, git, fs.recent_files)
    project.semantic_description = description
    project.updated_at = datetime.now(timezone.utc)
    if settings.SIGNAL_SEMANTIC:
        vec = embed_text(f"{project.name}. {description}")
        project.embedding = embedding_to_str(vec)

    db.commit()
    db.refresh(snapshot)

    from app.services.memory.memory_service import index_snapshot
    index_snapshot(db, project, snapshot)

    from app.services.code.code_search import index_code_symbols
    index_code_symbols(db, project, snapshot)

    from app.services.memory.event_service import diff_and_log_snapshot_events
    diff_and_log_snapshot_events(db, project, snapshot, previous_snapshot)

    return snapshot
