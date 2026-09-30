import os
import re
import json
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.project import Project, Snapshot
from app.services.snapshots.snapshot_service import create_snapshot, get_or_create_project
from app.services.retrieval.hybrid import hybrid_search
from app.services.retrieval.intent import extract_intent
from app.services.restoration.restoration_service import build_plan, execute_plan
from app.services.osassist import os_tools
from app.services.osassist import os_control
from app.services.memory import memory_service
from app.services.memory import event_service
from app.services.memory import timeline_service
from app.services.code import code_search
from app.services.memory import dashboard_service
from app.services.memory import mentor_service
from app.services.snapshots import scheduler
from app.services.chat.llm_intent import classify_with_llm, generate_chat_reply, extract_entity
from app.services.chat import access_control


@dataclass
class ChatResult:
    reply: str
    active_project_id: Optional[str] = None
    active_project_path: Optional[str] = None
    awaiting: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    unlocked: Optional[bool] = None


RESUME_WORDS = (
    "resume", "continue", "restore", "open project", "go back to", "pick up", "bring back",
    "take me back", "open the workspace", "workspace i was using", "open it again", "open again",
)
SAVE_WORDS = ("save", "remember", "snapshot", "checkpoint", "keep track of")
LIST_WORDS = ("what projects", "list projects", "my projects", "show projects", "which projects")
FILES_WORDS = ("what files", "which files", "show files", "recent files", "files in")
GIT_WORDS = ("git status", "what branch", "git branch", "modified files", "uncommitted")
FIND_WORDS = ("find file", "find a file", "search for", "locate")
DISK_WORDS = ("disk space", "storage", "how much space", "free space", "disk usage")
SYSTEM_WORDS = ("system info", "cpu", "memory usage", "ram", "how is my pc", "how is my computer", "performance", "battery")
PROCESS_WORDS = ("what's running", "whats running", "running processes", "top processes", "using the most memory", "what is running", "which processes")
DOWNLOADS_WORDS = ("recent downloads", "what did i download", "downloads folder")
OPEN_WORDS = ("open file", "open folder", "open this", "launch")
LISTDIR_WORDS = ("what's in", "whats in", "what's on my", "whats on my", "show me my", "contents of", "list files in")

# One combined trigger set for "find something specific I've seen before" -
# covers both per-file recall (existing MemoryItem search) and the newer
# persistent event history (git commits, browser pages, terminal commands,
# cross-project search). Kept as one intent instead of two, since they both
# answer the same kind of question and splitting them would just mean two
# word lists doing overlapping work.
RECALL_WORDS = (
    "give me the", "where did i", "where is the file", "where is", "where's", "what file did i",
    "which file was", "the file i", "the file for", "remind me of", "applied to", "sent to",
    "i was working on", "what was the last commit", "last commit i made", "last commit in",
    "what did i commit", "what was my last commit", "what did i change when", "which branch was i",
    "which project did i", "which project had", "what files did i change", "what files were changed",
    "which files did i", "which files were",
    "what tabs did i", "what pages was i", "what pages did i", "what documentation was i",
    "what documentation did i", "what github repo", "what repository was i", "what repository did i",
    "what github pages", "github pages", "was i looking at", "what pages was i looking",
    "what commands did i run", "what command did i use", "what did i run before", "what project was i",
    "what did i work on when", "when i implemented", "i implemented",
    "take me back to the project where", "that image", "that png", "that diagram", "the image i",
    "the png i", "the diagram i",
)
DIGEST_WORDS = ("what did i work on", "what have i been doing", "summarize my work", "recap", "catch me up", "what was i working on")
TIMELINE_EXTRA_WORDS = ("what happened", "timeline", "show me")
WEEKDAY_WORDS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "yesterday")
CODE_SEARCH_WORDS = (
    "find the code", "which function", "what function", "where is the code",
    "code responsible for", "code that handles", "code that sends", "function that",
)
DASHBOARD_WORDS = ("project health", "dashboard", "project status", "productivity dashboard", "project stats")
FORGET_WORDS = ("forget project", "delete project", "remove project", "stop tracking")
CHROME_STATUS_WORDS = ("is chrome connected", "check chrome", "chrome debug", "chrome status", "why aren't my tabs", "why arent my tabs", "tabs not saving", "tabs aren't saving")
SETPIN_WORDS = ("set pin", "set a pin", "enable access control", "lock my data", "lock access")
CLOSE_APP_WORDS = ("close ", "quit ", "kill the", "terminate the", "shut down ")
LOCK_SCREEN_WORDS = ("lock my screen", "lock the screen", "lock my pc", "lock my computer", "lock screen")
SCREENSHOT_WORDS = ("take a screenshot", "screenshot this", "capture my screen", "take screenshot", "screen capture")
MAKE_FOLDER_WORDS = ("create a folder", "make a folder", "new folder", "create folder")
DELETE_PATH_WORDS = ("delete file", "delete folder", "remove file", "delete this file", "delete the file", "delete the folder")
EMPTY_TRASH_WORDS = ("empty the recycle bin", "empty recycle bin", "empty trash", "clear recycle bin", "empty the trash")

PATH_RE = re.compile(r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+)")


def get_path(text):
    m = PATH_RE.search(text)
    if m:
        return m.group(0).rstrip(".,")
    return None


import re as _re


def contains_word(text, word):
    return _re.search(r"\b" + _re.escape(word) + r"\b", text) is not None


def classify(text):
    lowered = text.lower()
    if any(w in lowered for w in DASHBOARD_WORDS):
        return "dashboard"
    if any(w in lowered for w in CODE_SEARCH_WORDS):
        return "code_search"
    if any(w in lowered for w in SETPIN_WORDS):
        return "set_pin"
    if any(w in lowered for w in CHROME_STATUS_WORDS):
        return "chrome_status"
    if any(w in lowered for w in EMPTY_TRASH_WORDS):
        return "empty_trash"
    if any(w in lowered for w in DELETE_PATH_WORDS):
        return "delete_path"
    if any(w in lowered for w in MAKE_FOLDER_WORDS):
        return "make_folder"
    if any(w in lowered for w in SCREENSHOT_WORDS):
        return "screenshot"
    if any(w in lowered for w in LOCK_SCREEN_WORDS):
        return "lock_screen"
    if any(w in lowered for w in CLOSE_APP_WORDS):
        return "close_app"
    if any(w in lowered for w in FORGET_WORDS):
        return "forget"
    if any(w in lowered for w in DOWNLOADS_WORDS):
        return "downloads"
    if any(w in lowered for w in LISTDIR_WORDS):
        return "listdir"
    if any(w in lowered for w in PROCESS_WORDS):
        return "processes"
    if any(w in lowered for w in DISK_WORDS):
        return "disk"
    if any(contains_word(lowered, w) if len(w) <= 3 else w in lowered for w in SYSTEM_WORDS):
        return "system"
    if any(w in lowered for w in FIND_WORDS):
        return "find"
    if any(w in lowered for w in OPEN_WORDS):
        return "open"
    if any(w in lowered for w in SAVE_WORDS):
        return "save"
    if any(w in lowered for w in RESUME_WORDS):
        return "resume"
    if any(w in lowered for w in RECALL_WORDS):
        return "recall"
    if any(day in lowered for day in WEEKDAY_WORDS) and (
        any(w in lowered for w in DIGEST_WORDS) or any(w in lowered for w in TIMELINE_EXTRA_WORDS)
    ):
        return "timeline"
    if any(w in lowered for w in DIGEST_WORDS):
        return "digest"
    if any(w in lowered for w in LIST_WORDS):
        return "list"
    if any(w in lowered for w in FILES_WORDS):
        return "files"
    if any(w in lowered for w in GIT_WORDS):
        return "git"
    if lowered.startswith("open "):
        return "open"
    return "general"


def resolve_project(db, text, active_project_id):
    path = get_path(text)
    if path and os.path.isdir(path):
        return get_or_create_project(db, path)

    intent = extract_intent(text)
    if intent.query.strip():
        ranked = hybrid_search(db, intent.query, top_k=1)
        if ranked:
            return ranked[0].project

    if active_project_id:
        return db.query(Project).filter(Project.id == active_project_id).first()

    return None


def strip_command_word(text, words):
    lowered = text.lower()
    for w in words:
        idx = lowered.find(w)
        if idx != -1:
            rest = text[idx + len(w):].strip()
            if rest:
                return rest
    return text.strip()


def strip_quotes(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("\"", "'"):
        text = text[1:-1].strip()
    return text


def format_event_reply(db, event, score):
    project = db.query(Project).filter(Project.id == event.project_id).first() if event.project_id else None
    project_name = project.name if project else "a project I don't have saved anymore"
    when = event.created_at.strftime("%b %d, %I:%M %p")

    if event.event_type == "git_commit":
        reply = f"In **{project_name}**, you committed \"{event.title}\" on {when}."
        if event.meta:
            meta = json.loads(event.meta)
            changed = meta.get("changed_files") or []
            if changed:
                reply += f" Changed files: {', '.join(changed[:5])}."
        return reply

    if event.source == "chrome":
        return f"You had **{event.title or event.path}** open in **{project_name}** on {when}.\n{event.path}"

    if event.source == "file":
        verb = event.event_type.replace("_", " ")
        return f"Found it in **{project_name}**:\n{event.path}\nYou {verb} it on {when}."

    if event.source == "terminal":
        return f"In **{project_name}**, you ran: `{event.description}` on {when}."

    if event.source == "git":
        return f"In **{project_name}**: {event.title or event.description} ({when})."

    return f"In **{project_name}**: {event.title or event.description} on {when}."


def recall_reply(db, message, active_project_id):
    mem_hits = memory_service.recall(db, message, top_k=3)
    event_hits = event_service.search_events(db, message, current_project_id=active_project_id, time_range_text=message, top_k=3)

    best_mem = mem_hits[0] if mem_hits else None
    best_event = event_hits[0] if event_hits else None
    mem_score = best_mem[1] if best_mem else 0
    event_score = best_event[1] if best_event else 0

    if not best_mem and not best_event:
        return ChatResult(
            "I don't have anything saved that matches that. If it's from a project I haven't saved yet, "
            "say \"save\" while that project is open and I'll remember it going forward."
        )

    if mem_score >= event_score and mem_score >= 0.35:
        item, score = best_mem
        project = db.query(Project).filter(Project.id == item.project_id).first()
        project_name = project.name if project else "a saved project"
        ok, err = os_tools.open_path(item.locator)
        if ok:
            return ChatResult(
                f"That's from **{project_name}** — opening it now: {item.locator}",
                active_project_id=item.project_id, active_project_path=project.path if project else None,
            )
        return ChatResult(
            f"That's from **{project_name}**: {item.locator} (couldn't auto-open it: {err})",
            active_project_id=item.project_id, active_project_path=project.path if project else None,
        )

    if best_event and event_score >= 0.15:
        event, score = best_event
        project = db.query(Project).filter(Project.id == event.project_id).first() if event.project_id else None
        return ChatResult(
            format_event_reply(db, event, score),
            active_project_id=event.project_id, active_project_path=project.path if project else None,
        )

    return ChatResult(
        "I don't have anything saved that matches that clearly. Try describing it differently, "
        "or save the project first if I haven't seen it yet."
    )


def launch_app_reply(app_name):
    if not app_name:
        return ChatResult("Which app should I open?")
    ok, err = os_control.launch_app(app_name)
    if ok:
        return ChatResult(f"Opening {app_name}.")
    return ChatResult(f"Couldn't open {app_name}: {err}")


def format_action_required(skipped_items):
    high_risk = [i for i in skipped_items if i["action"]["type"] == "run_command"]
    routine = [i for i in skipped_items if i["action"]["type"] != "run_command"]

    parts = []
    if routine:
        lines = "\n".join(f"✓ {i['description']}" for i in routine)
        parts.append(f"⚠ ACTION REQUIRED\nPCM wants to:\n{lines}\nReply \"yes\" to approve, or \"no\" to skip.")
    for item in high_risk:
        cmd = item["action"]["command"]
        parts.append(
            f"⚠ HIGH-RISK ACTION\n{cmd}\nThis will run a command from your terminal history — "
            f"it hasn't been checked beyond the basic blocklist. Reply \"yes\" to confirm, or \"no\" to skip."
        )
    return "\n\n".join(parts)


def run_confirmed_action(action, target):
    if action == "resume_unsafe":
        executed, warnings, skipped = execute_plan(target, confirm_unsafe=True)
        if executed:
            reply = "Done — restored: " + ", ".join(executed) + "."
        else:
            reply = "Nothing further could be restored."
        if warnings:
            reply += "\n\n⚠ " + " / ".join(warnings)
        return ChatResult(reply)
    if action == "close_app":
        ok, result = os_control.close_app(target)
        if ok:
            return ChatResult(f"Closed: {result}")
        return ChatResult(f"Couldn't close {target}: {result}")
    if action == "delete_path":
        ok, err = os_control.delete_path(target)
        if ok:
            return ChatResult(f"Deleted {target}")
        return ChatResult(f"Couldn't delete that: {err}")
    if action == "empty_trash":
        ok, err = os_control.empty_recycle_bin()
        if ok:
            return ChatResult("Recycle bin emptied.")
        return ChatResult(f"Couldn't empty the recycle bin: {err}")
    return ChatResult("I lost track of what to confirm — try that again.")


def do_save(db, path, selected_tab_urls=None, chrome_note=None):
    snapshot = create_snapshot(db, path, trigger="chat")
    project = get_or_create_project(db, path)
    scheduler.set_active_path(path)

    if selected_tab_urls is not None:
        from app.models.project import MemoryItem
        removed_urls = []
        for tab in list(snapshot.browser_tabs):
            if tab.url not in selected_tab_urls:
                removed_urls.append(tab.url)
                db.delete(tab)
        if removed_urls:
            db.query(MemoryItem).filter(
                MemoryItem.snapshot_id == snapshot.id,
                MemoryItem.kind == "tab",
                MemoryItem.locator.in_(removed_urls),
            ).delete(synchronize_session=False)
        db.commit()
        db.refresh(snapshot)

    n_files = len(snapshot.files)
    branch = snapshot.git_context.branch if snapshot.git_context else None
    n_tabs = len(snapshot.browser_tabs)
    details = [f"{n_files} recent file(s)"]
    if branch:
        details.append(f"Git branch `{branch}`")
    if n_tabs:
        details.append(f"{n_tabs} browser tab(s)")
    reply = f"Saved **{project.name}**. I've got {', '.join(details)}. Just say \"resume {project.name}\" any time."
    if chrome_note:
        reply += f"\n\n({chrome_note})"

    previous_snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.project_id == project.id, Snapshot.id != snapshot.id)
        .order_by(Snapshot.created_at.desc())
        .first()
    )
    notes = mentor_service.build_mentor_notes(project, snapshot, previous_snapshot)
    for note in notes:
        reply += f"\n\n{note}"

    event_service.log_project_event(db, project, "project_saved")
    return ChatResult(reply, active_project_id=project.id, active_project_path=project.path)


def propose_tab_selection(path):
    from app.services.workspace.chrome_context import collect_chrome_context
    from app.services.workspace.misinfo_check import check_url
    chrome = collect_chrome_context()

    if chrome.status != "ok":
        note = (
            f"Chrome tabs could not be accessed. Chrome remote debugging is not available on "
            f"127.0.0.1:9222 ({chrome.reason}). Ask me \"check chrome\" for how to fix that."
        )
        return None, note

    if not chrome.tabs:
        return None, "Chrome is connected but has no open tabs right now."

    numbered = []
    for i, t in enumerate(chrome.tabs):
        warning = check_url(t.url, title=t.title)
        numbered.append({"index": i + 1, "title": t.title or t.url, "url": t.url, "warning": warning})

    lines = []
    for t in numbered:
        line = f"{t['index']}. {t['title']}"
        if t["warning"]:
            line += f"  \u26a0 {t['warning']}"
        lines.append(line)

    reply = (
        f"I found {len(numbered)} open Chrome tab(s):\n\n" + "\n".join(lines) + "\n\n"
        f"Which ones belong to this project? Reply with numbers (e.g. \"1,3\"), \"all\", or \"none\"."
    )
    return ChatResult(reply, awaiting="select_tabs", data={"path": path, "tabs": numbered}), None


def chrome_status_reply():
    from app.services.workspace.chrome_context import collect_chrome_context
    chrome = collect_chrome_context()

    if chrome.status == "ok":
        body = f"Chrome debugging: available\nEndpoint: 127.0.0.1:9222\nDetected tabs: {len(chrome.tabs)}"
        if chrome.tabs:
            lines = "\n".join(f"- {t.title} — {t.url}" for t in chrome.tabs)
            body += "\n\n" + lines
        return ChatResult(body)

    return ChatResult(
        f"Chrome debugging: unavailable\nEndpoint: 127.0.0.1:9222\nReason: {chrome.reason}\n\n"
        "This almost always means Chrome was already running when you added the flag — it's a "
        "single-process app, so a second launch with --remote-debugging-port just opens a new window "
        "inside the existing process and ignores the flag.\n\n"
        "Fix: close every Chrome window completely (check Task Manager for lingering chrome.exe), then "
        "relaunch with:\n\n`chrome.exe --remote-debugging-port=9222 --user-data-dir=\"$env:TEMP\\pcm-chrome\"`\n\n"
        "Then ask me to save again."
    )


def parse_tab_selection(message, tabs):
    lowered = message.strip().lower()
    if lowered in ("all", "all of them", "yes", "everything"):
        return [t["url"] for t in tabs]
    if lowered in ("none", "no", "skip"):
        return []
    picked = []
    for chunk in re.split(r"[,\s]+", message):
        chunk = chunk.strip()
        if chunk.isdigit():
            idx = int(chunk)
            match = next((t for t in tabs if t["index"] == idx), None)
            if match:
                picked.append(match["url"])
    return picked


def handle_message(db: Session, message: str, active_project_id: Optional[str] = None, awaiting: Optional[str] = None, context: Optional[Dict[str, Any]] = None, unlocked: bool = False) -> ChatResult:
    if awaiting == "enter_pin" and context:
        if not access_control.check_pin(db, message.strip()):
            return ChatResult("That PIN didn't match. Try again.", awaiting="enter_pin", data=context)
        pending_message = context.get("pending_message", "")
        result = handle_message(db, pending_message, active_project_id=active_project_id, unlocked=True)
        result.unlocked = True
        return result

    if awaiting == "confirm_action" and context:
        lowered = message.strip().lower()
        if lowered not in ("yes", "y", "confirm", "do it", "yes please"):
            return ChatResult("Okay, not doing that.")
        return run_confirmed_action(context.get("action"), context.get("target"))

    if awaiting == "save_path":
        path = get_path(message) or strip_quotes(message)
        if not path or not os.path.isdir(path):
            return ChatResult(
                f"I still can't find that folder: `{path}`. Give me the full path, e.g. `C:\\Projects\\MyApp`.",
                awaiting="save_path",
            )
        proposal, chrome_note = propose_tab_selection(path)
        if proposal:
            return proposal
        return do_save(db, path, chrome_note=chrome_note)

    if awaiting == "select_tabs" and context:
        path = context.get("path")
        tabs = context.get("tabs", [])
        if not path or not os.path.isdir(path):
            return ChatResult("I lost track of the folder — let's start over. Say \"save\" again.")
        selected = parse_tab_selection(message, tabs)
        return do_save(db, path, selected_tab_urls=selected)

    kind = classify_with_llm(message) or classify(message)

    if kind == "set_pin":
        digits = re.search(r"\d{4,8}", message)
        if not digits:
            return ChatResult("Give me a 4-8 digit PIN, e.g. \"set pin 4821\".")
        access_control.set_pin(db, digits.group(0))
        return ChatResult("PIN set. I'll ask for it before showing saved files, history, or projects from now on.")

    if access_control.is_gated(kind) and access_control.is_configured(db) and not unlocked:
        return ChatResult(
            "This needs your PIN to continue.",
            awaiting="enter_pin",
            data={"pending_kind": kind, "pending_message": message},
        )

    if kind == "find":
        keyword = strip_command_word(message, FIND_WORDS)
        keyword = keyword.strip("? .")
        if not keyword:
            return ChatResult("What should I search for?")
        matches = os_tools.find_files(keyword)
        if not matches:
            return ChatResult(f"Couldn't find anything named like \"{keyword}\" in your usual folders (Desktop, Documents, Downloads).")
        lines = "\n".join(f"• {m}" for m in matches[:15])
        more = f"\n\n(showing first 15 of {len(matches)})" if len(matches) > 15 else ""
        return ChatResult(f"Found {len(matches)} match(es) for \"{keyword}\":\n\n{lines}{more}")

    if kind == "recall":
        return recall_reply(db, message, active_project_id)

    if kind == "open":
        path = get_path(message)
        if not path:
            app_name = strip_command_word(message, OPEN_WORDS).strip("? .")
            if app_name:
                return launch_app_reply(app_name)
            return ChatResult("Give me the full path of what to open, or the name of an app.")
        if not os.path.exists(path):
            return ChatResult(f"That path doesn't exist: {path}")
        ok, err = os_tools.open_path(path)
        if ok:
            return ChatResult(f"Opened {path}")
        return ChatResult(f"Couldn't open it: {err}")

    if kind == "launch_app":
        app_name = extract_entity(message, "application name") or strip_command_word(message, ("open", "launch", "start"))
        app_name = app_name.strip("? .")
        return launch_app_reply(app_name)

    if kind == "close_app":
        app_name = extract_entity(message, "application name") or strip_command_word(message, CLOSE_APP_WORDS)
        app_name = app_name.strip("? .")
        if not app_name:
            return ChatResult("Which app should I close?")
        return ChatResult(
            f"⚠ HIGH-RISK ACTION\nClose every running \"{app_name}\" process\n"
            f"This can't be undone if you have unsaved work in it. Reply \"yes\" to confirm, or \"no\" to cancel.",
            awaiting="confirm_action",
            data={"action": "close_app", "target": app_name},
        )

    if kind == "lock_screen":
        ok, err = os_control.lock_screen()
        if ok:
            return ChatResult("Locking your screen now.")
        return ChatResult(f"Couldn't lock the screen: {err}")

    if kind == "screenshot":
        ok, result = os_control.take_screenshot()
        if ok:
            return ChatResult(f"Saved a screenshot to {result}")
        return ChatResult(f"Couldn't take a screenshot: {result}")

    if kind == "make_folder":
        path = get_path(message) or extract_entity(message, "folder path to create")
        if not path:
            return ChatResult("What should the new folder's full path be?")
        ok, err = os_control.make_folder(path)
        if ok:
            return ChatResult(f"Created {path}")
        return ChatResult(f"Couldn't create that folder: {err}")

    if kind == "delete_path":
        path = get_path(message) or extract_entity(message, "file or folder path to delete")
        if not path:
            return ChatResult("Give me the full path of what to delete.")
        return ChatResult(
            f"⚠ HIGH-RISK ACTION\n{path}\nThis will permanently delete that file or folder. Reply \"yes\" to confirm, or \"no\" to cancel.",
            awaiting="confirm_action",
            data={"action": "delete_path", "target": path},
        )

    if kind == "empty_trash":
        return ChatResult(
            "⚠ HIGH-RISK ACTION\nEmpty the recycle bin\nThis permanently deletes everything in it. Reply \"yes\" to confirm, or \"no\" to cancel.",
            awaiting="confirm_action",
            data={"action": "empty_trash", "target": None},
        )

    if kind == "disk":
        drives = os_tools.disk_usage_summary()
        if not drives:
            return ChatResult("Couldn't read disk usage on this machine.")
        lines = []
        for d in drives:
            lines.append(f"• {d['drive']} — {d['free_gb']} GB free of {d['total_gb']} GB")
        return ChatResult("Here's your storage:\n\n" + "\n".join(lines))

    if kind == "system":
        info = os_tools.system_summary()
        reply = f"You're on {info['os']} ({info['machine']})."
        if "cpu_percent" in info:
            reply += f" CPU is at {info['cpu_percent']}%, memory is {info['memory_used_percent']}% used ({info['memory_available_gb']} GB free of {info['memory_total_gb']} GB)."
        if info.get("battery_percent") is not None:
            reply += f" Battery is at {info['battery_percent']}%."
        return ChatResult(reply)

    if kind == "processes":
        procs = os_tools.top_processes()
        if not procs:
            return ChatResult("Couldn't read running processes on this machine.")
        lines = "\n".join(f"• {name} — {mem}% memory" for name, mem in procs)
        return ChatResult("Top processes by memory use:\n\n" + lines)

    if kind == "downloads":
        files = os_tools.recent_downloads()
        if not files:
            return ChatResult("No downloads found, or I couldn't find your Downloads folder.")
        lines = "\n".join(f"• {os.path.basename(f)}" for f in files)
        return ChatResult("Your most recent downloads:\n\n" + lines)

    if kind == "listdir":
        path = get_path(message)
        if not path:
            for name in ["desktop", "documents", "downloads", "pictures", "music", "videos", "home"]:
                if name in message.lower():
                    path = os_tools.known_folder(name)
                    break
        if not path:
            return ChatResult("Which folder? You can say something like \"what's on my desktop\" or give me a full path.")
        entries = os_tools.list_directory(path)
        if entries is None:
            return ChatResult(f"That folder doesn't exist: {path}")
        if not entries:
            return ChatResult(f"{path} is empty.")
        lines = "\n".join(f"• {'📁 ' if e['is_dir'] else ''}{e['name']}" for e in entries)
        return ChatResult(f"Here's what's in {path}:\n\n{lines}")

    if kind == "chrome_status":
        return chrome_status_reply()

    if kind == "dashboard":
        project = resolve_project(db, message, active_project_id)
        if not project:
            return ChatResult("I don't know which project you mean yet — save one first, or name it.")
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.project_id == project.id)
            .order_by(Snapshot.created_at.desc())
            .first()
        )
        if not snapshot:
            return ChatResult(f"I don't have a saved snapshot of **{project.name}** yet — say \"save\" to create one.")
        return ChatResult(
            dashboard_service.build_dashboard(db, project, snapshot),
            active_project_id=project.id, active_project_path=project.path,
        )

    if kind == "code_search":
        hits = code_search.search_code(db, message, top_k=5)
        if not hits:
            return ChatResult("I couldn't find any indexed code matching that. Save the project again so I can index its files.")
        by_file = {}
        for item, score in hits:
            path, _, name = item.locator.rpartition("::")
            by_file.setdefault(path, []).append(name)
        lines = []
        for path, names in by_file.items():
            lines.append(f" {os.path.basename(path)}")
            for name in names:
                lines.append(f" └── {name}()")
        return ChatResult("\n".join(lines))

    if kind == "timeline":
        events, start = timeline_service.build_timeline(db, message, project_id=active_project_id)
        if events is None:
            return ChatResult("Which day? Try \"what did I work on Tuesday\" or \"yesterday\".")
        return ChatResult(timeline_service.format_timeline_reply(events, start))

    if kind == "digest":
        cutoff_days = 7 if "week" in message.lower() else 1
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        recent = (
            db.query(Snapshot)
            .filter(Snapshot.created_at >= cutoff)
            .order_by(Snapshot.created_at.desc())
            .all()
        )
        if not recent:
            return ChatResult("No saved activity in that time range yet.")
        seen = {}
        for s in recent:
            seen.setdefault(s.project_id, s)
        lines = []
        for project_id, snap in seen.items():
            proj = db.query(Project).filter(Project.id == project_id).first()
            if not proj:
                continue
            branch = snap.git_context.branch if snap.git_context else None
            piece = f"• **{proj.name}**"
            if branch:
                piece += f" (branch `{branch}`)"
            piece += f" — last touched {snap.created_at.strftime('%b %d, %I:%M %p')}"
            lines.append(piece)
        span = "week" if cutoff_days == 7 else "day"
        return ChatResult(f"Here's what you touched in the last {span}:\n\n" + "\n".join(lines))

    if kind == "forget":
        name = strip_command_word(message, FORGET_WORDS).strip("? .")
        if not name:
            return ChatResult("Which project should I forget?")
        ranked = hybrid_search(db, name, top_k=1)
        if not ranked:
            return ChatResult(f"I don't have a project matching \"{name}\".")
        project = ranked[0].project
        db.query(Snapshot).filter(Snapshot.project_id == project.id).delete()
        db.query(Project).filter(Project.id == project.id).delete()
        db.commit()
        return ChatResult(f"Forgot **{project.name}** — deleted everything I had saved for it.")

    if kind == "list":
        projects = db.query(Project).order_by(Project.updated_at.desc()).limit(10).all()
        if not projects:
            return ChatResult("You don't have any saved projects yet. Tell me a folder to save and I'll remember it.")
        lines = [f"• **{p.name}** — {p.semantic_description or p.path}" for p in projects]
        return ChatResult("Here's what I have saved:\n\n" + "\n".join(lines))

    if kind == "save":
        path = get_path(message)
        if not path and active_project_id:
            project = db.query(Project).filter(Project.id == active_project_id).first()
            path = project.path if project else None
        if not path:
            path = os_tools.detect_recent_vscode_folder()
            auto_detected = bool(path)
        else:
            auto_detected = False

        if not path:
            return ChatResult(
                "Which folder should I save? Give me the full path, e.g. `C:\\Projects\\MyApp`.",
                awaiting="save_path",
            )
        if not os.path.isdir(path):
            return ChatResult(f"I can't find that folder: `{path}`. Double-check the path and try again.", awaiting="save_path")

        proposal, chrome_note = propose_tab_selection(path)
        if proposal:
            if auto_detected:
                proposal.reply = "(Detected your open VS Code folder) " + proposal.reply
            return proposal

        result = do_save(db, path, chrome_note=chrome_note)
        if auto_detected:
            result.reply = "(Detected your open VS Code folder) " + result.reply
        return result

    if kind in ("files", "git"):
        project = resolve_project(db, message, active_project_id)
        if not project:
            return ChatResult("I don't know which project you mean yet — save one first, or name it.")
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.project_id == project.id)
            .order_by(Snapshot.created_at.desc())
            .first()
        )
        if not snapshot:
            return ChatResult(f"I don't have a saved snapshot of **{project.name}** yet — say \"save\" to create one.")

        if kind == "files":
            if not snapshot.files:
                return ChatResult(f"No recent files recorded for **{project.name}**.")
            lines = [f"• {f.path}" for f in snapshot.files[:10]]
            return ChatResult(
                f"Recent files in **{project.name}**:\n\n" + "\n".join(lines),
                active_project_id=project.id, active_project_path=project.path,
            )
        else:
            gc = snapshot.git_context
            if not gc or not gc.branch:
                return ChatResult(f"No Git repository detected for **{project.name}**.")
            modified = [f for f in (gc.modified_files or "").split("\n") if f]
            msg = f"**{project.name}** is on branch `{gc.branch}`."
            if gc.last_commit_message:
                msg += f" Last commit: \"{gc.last_commit_message}\"."
            if modified:
                msg += f" {len(modified)} modified file(s) not committed."
            return ChatResult(msg, active_project_id=project.id, active_project_path=project.path)

    if kind == "resume":
        project = resolve_project(db, message, active_project_id)
        if not project:
            return ChatResult("I couldn't find a matching saved project. Try \"save <folder path>\" first.")

        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.project_id == project.id)
            .order_by(Snapshot.created_at.desc())
            .first()
        )
        if not snapshot:
            return ChatResult(f"I found **{project.name}** but have no saved snapshot for it yet. Say \"save\" first.")

        scheduler.set_active_path(project.path)
        event_service.log_project_event(db, project, "project_resumed")
        plan = build_plan(project.path, snapshot)
        executed, warnings, skipped = execute_plan(plan, confirm_unsafe=False)

        if executed:
            reply = f"Resuming **{project.name}** — brought back " + ", ".join(executed) + "."
        else:
            reply = f"Getting **{project.name}** ready — nothing safe to restore on its own yet."

        if skipped:
            reply += "\n\n" + format_action_required(skipped)
            return ChatResult(
                reply, active_project_id=project.id, active_project_path=project.path,
                awaiting="confirm_action",
                data={"action": "resume_unsafe", "target": skipped, "project_id": project.id, "project_path": project.path},
            )

        if warnings:
            reply += "\n\n⚠ " + " / ".join(warnings)

        return ChatResult(
            reply, active_project_id=project.id, active_project_path=project.path,
            data={"executed": executed, "warnings": warnings},
        )

    project = resolve_project(db, message, active_project_id) if active_project_id else None
    if project:
        return ChatResult(
            f"We're currently looking at **{project.name}** ({project.path}). "
            f"You can ask me to resume it, save its current state, or ask about its files/git status. "
            f"I can also search your machine for files, check disk space, or tell you what's using memory."
        )

    hits = memory_service.recall(db, message, top_k=1)
    if hits and hits[0][1] >= 0.45:
        item, score = hits[0]
        proj = db.query(Project).filter(Project.id == item.project_id).first()
        proj_name = proj.name if proj else "a saved project"
        return ChatResult(f"That sounds like something from **{proj_name}**: {item.locator}. Want me to open it?")

    event_hits = event_service.search_events(db, message, current_project_id=active_project_id, time_range_text=message, top_k=1)
    if event_hits and event_hits[0][1] >= 0.4:
        event, score = event_hits[0]
        return ChatResult(format_event_reply(db, event, score))

    chat_reply = generate_chat_reply(message)
    if chat_reply:
        return ChatResult(chat_reply)

    return ChatResult(
        "I can save a project's context and resume it later, answer questions about your saved projects, "
        "or act like a light OS assistant — find files, check disk space, list top processes, open a folder. "
        "Try: \"save C:\\Projects\\MyApp\", \"resume MyApp\", \"find file report.docx\", or \"how much disk space do I have\"."
    )
