import os
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

TODO_PATTERN = re.compile(r"#\s*TODO|//\s*TODO|TODO:", re.IGNORECASE)
CODE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".md")


def count_todos_in_snapshot(snapshot):
    total = 0
    for f in snapshot.files:
        ext = os.path.splitext(f.path)[1].lower()
        if ext not in CODE_EXTENSIONS:
            continue
        try:
            with open(f.path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
        except OSError:
            continue
        total += len(TODO_PATTERN.findall(content))
    return total


def most_modified_files(db, project_id, days=14):
    from app.models.project import Event
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    events = (
        db.query(Event)
        .filter(Event.project_id == project_id, Event.source == "file")
        .filter(Event.created_at >= cutoff)
        .all()
    )
    counts = Counter(e.path for e in events if e.path)
    return counts.most_common(5)


def recent_commit_count(db, project_id, days=14):
    from app.models.project import Event
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(Event)
        .filter(Event.project_id == project_id, Event.event_type == "git_commit")
        .filter(Event.created_at >= cutoff)
        .count()
    )


def build_dashboard(db, project, snapshot):
    todos = count_todos_in_snapshot(snapshot)
    uncommitted = 0
    branch = None
    if snapshot.git_context:
        branch = snapshot.git_context.branch
        modified = [f for f in (snapshot.git_context.modified_files or "").split("\n") if f]
        untracked = [f for f in (snapshot.git_context.untracked_files or "").split("\n") if f]
        uncommitted = len(modified) + len(untracked)

    commits = recent_commit_count(db, project.id)
    hot_files = most_modified_files(db, project.id)

    lines = []
    lines.append(f"PROJECT HEALTH — {project.name}")
    lines.append(f"Open TODOs             {todos}")
    lines.append(f"Uncommitted changes    {uncommitted}")
    lines.append(f"Recent commits (14d)   {commits}")
    if branch:
        lines.append(f"Current branch         {branch}")
    lines.append("Failed tests           not available (PCM doesn't run your test suite)")
    lines.append("Documentation coverage not available (needs deeper code analysis)")

    if hot_files:
        lines.append("")
        lines.append("Most modified files recently:")
        for path, count in hot_files:
            lines.append(f"  {os.path.basename(path)} ({count}x)")

    return "\n".join(lines)
