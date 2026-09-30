import httpx
from app.config import settings

VALID_KINDS = (
    "save", "resume", "recall", "digest", "forget", "list", "files", "git",
    "find", "open", "listdir", "disk", "system", "processes", "downloads",
    "chrome_status", "launch_app", "close_app", "lock_screen", "screenshot",
    "make_folder", "delete_path", "empty_trash", "general",
)

INTENT_PROMPT = """You classify a user's message to a developer workspace assistant into exactly one label.

save - user wants to save/remember/snapshot their current project
resume - user wants to resume/restore/reopen a previously saved project
recall - user is asking about something specific from the past: a file, a git commit, a browser tab/page they had open, a terminal command
digest - user wants a broad summary of recent work
forget - user wants to delete a saved project
list - user wants a list of all saved projects
files - user wants the list of files in the currently active project
git - user wants git status/branch info for the currently active project
find - user wants to search their filesystem for a file by name
open - user wants to open a specific file or folder path directly
listdir - user wants to see what's inside a folder
disk - user is asking about disk space
system - user is asking about CPU, memory, battery, general system info
processes - user is asking what's using memory or what's running
downloads - user is asking about recent downloads
chrome_status - user is asking whether Chrome debugging is connected
launch_app - user wants to open/launch/start a desktop application by name, not a file or folder
close_app - user wants to close/quit/kill a running application
lock_screen - user wants to lock their screen/computer
screenshot - user wants to take a screenshot
make_folder - user wants to create a new folder
delete_path - user wants to delete a specific file or folder
empty_trash - user wants to empty the recycle bin
general - anything else, including greetings or casual conversation

Reply with only the single label word, nothing else."""


def call_anthropic(message, system_prompt, max_tokens):
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.LLM_MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": message}],
        },
        timeout=8.0,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def call_grok(message, system_prompt, max_tokens):
    resp = httpx.post(
        "https://api.x.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.GROK_API_KEY}",
            "content-type": "application/json",
        },
        json={
            "model": settings.GROK_MODEL,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        },
        timeout=8.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def active_provider():
    if settings.LLM_PROVIDER == "grok" and settings.GROK_API_KEY:
        return "grok"
    if settings.LLM_PROVIDER == "anthropic" and settings.LLM_API_KEY:
        return "anthropic"
    if settings.GROK_API_KEY:
        return "grok"
    if settings.LLM_API_KEY:
        return "anthropic"
    return None


def classify_with_llm(message):
    if not settings.LLM_ENABLED:
        return None

    provider = active_provider()
    if provider is None:
        return None

    try:
        if provider == "grok":
            label = call_grok(message, INTENT_PROMPT, 10)
        else:
            label = call_anthropic(message, INTENT_PROMPT, 10)
        label = label.strip().lower()
    except Exception:
        return None

    if label in VALID_KINDS:
        return label
    return None


CHAT_SYSTEM_PROMPT = """You are the conversational layer of a local developer workspace assistant called PCM.
You help save and resume coding projects, search files, and answer questions about the user's machine.
Keep replies short, friendly, and to the point. If the user's message sounds like it wants one of your
real features (saving a project, resuming one, finding a file, checking disk space), say so plainly and
tell them what to say instead of pretending to do it yourself."""


def generate_chat_reply(message):
    if not settings.LLM_ENABLED:
        return None

    provider = active_provider()
    if provider is None:
        return None

    try:
        if provider == "grok":
            return call_grok(message, CHAT_SYSTEM_PROMPT, 200)
        return call_anthropic(message, CHAT_SYSTEM_PROMPT, 200)
    except Exception:
        return None


ENTITY_PROMPT = "Extract only the {label} the user is referring to from their message. Reply with just that, nothing else, no punctuation or explanation."


def extract_entity(message, label):
    if not settings.LLM_ENABLED:
        return None

    provider = active_provider()
    if provider is None:
        return None

    prompt = ENTITY_PROMPT.format(label=label)
    try:
        if provider == "grok":
            value = call_grok(message, prompt, 30)
        else:
            value = call_anthropic(message, prompt, 30)
    except Exception:
        return None

    value = value.strip().strip('"').strip("'")
    if not value or len(value) > 200:
        return None
    return value
