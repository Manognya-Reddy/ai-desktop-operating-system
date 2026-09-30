import re
from datetime import datetime, timezone, timedelta
from app.models.project import Event, Project

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

EVENT_VERBS = {
    "file_created": "Created",
    "file_modified": "Modified",
    "file_deleted": "Deleted",
    "file_renamed": "Renamed",
    "git_commit": "Committed",
    "git_branch_changed": "Switched to branch",
    "browser_tab_opened": "Opened",
    "terminal_command": "Ran",
    "vscode_workspace_opened": "Opened workspace",
    "project_saved": "Saved",
    "project_resumed": "Resumed",
}


def resolve_day_range(query):
    lowered = query.lower()
    now = datetime.now(timezone.utc)
    if "today" in lowered:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if "yesterday" in lowered:
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        return start, end
    for i, day in enumerate(WEEKDAYS):
        if day in lowered:
            today_index = now.weekday()
            days_back = (today_index - i) % 7
            days_back = 7 if days_back == 0 else days_back
            target = now - timedelta(days=days_back)
            start = target.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return start, end
    return None


def describe_event(event):
    verb = EVENT_VERBS.get(event.event_type, event.event_type.replace("_", " "))
    label = event.title or event.description or event.path or ""
    if event.event_type == "git_commit":
        return f"{verb} \"{label}\""
    return f"{verb} {label}"


def build_timeline(db, query, project_id=None):
    day_range = resolve_day_range(query)
    if not day_range:
        return None
    start, end = day_range

    q = db.query(Event).filter(Event.created_at >= start, Event.created_at < end)
    if project_id:
        q = q.filter(Event.project_id == project_id)
    events = q.order_by(Event.created_at.asc()).all()

    if not events:
        return [], start
    return events, start


def format_timeline_reply(events, start):
    if not events:
        return f"Nothing recorded for {start.strftime('%A, %b %d')}."

    by_project = {}
    for e in events:
        by_project.setdefault(e.project_id, []).append(e)

    lines = [f"Here's what happened on {start.strftime('%A, %b %d')}:"]
    for project_id, project_events in by_project.items():
        lines.append("")
        seen = set()
        for e in project_events:
            desc = describe_event(e)
            if desc in seen:
                continue
            seen.add(desc)
            lines.append(f"-> {desc}")
    return "\n".join(lines)
