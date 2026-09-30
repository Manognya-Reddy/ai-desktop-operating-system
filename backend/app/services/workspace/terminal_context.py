import os
import platform
from dataclasses import dataclass, field
from typing import List

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

DANGEROUS_PATTERNS = ("rm -rf", "format ", "del /f", "rd /s", "> /dev/", "mkfs")
MAX_COMMANDS = 10
SHELL_NAMES = ("powershell.exe", "cmd.exe", "pwsh.exe", "bash", "zsh", "sh")


@dataclass
class TerminalSnapshot:
    working_directory: str
    recent_commands: List[str] = field(default_factory=list)
    active_venv: str = None
    running_processes: List[str] = field(default_factory=list)


def _powershell_history_path():
    return os.path.expanduser(
        r"~\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"
    )


def _is_safe_to_log(cmd):
    lowered = cmd.lower()
    return not any(p in lowered for p in DANGEROUS_PATTERNS)


def _find_shell_children(cwd):
    if not HAS_PSUTIL:
        return []
    found = []
    for p in psutil.process_iter(["name", "cwd", "ppid"]):
        try:
            name = (p.info.get("name") or "").lower()
            pcwd = p.info.get("cwd") or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in SHELL_NAMES:
            continue
        try:
            if pcwd and os.path.normcase(pcwd).startswith(os.path.normcase(cwd)):
                found.append(p.info.get("name"))
        except Exception:
            continue
    return list(set(found))[:5]


def collect_terminal_context(cwd=None):
    cwd = cwd or os.getcwd()
    commands = []

    if platform.system() == "Windows":
        hist_path = _powershell_history_path()
        if os.path.isfile(hist_path):
            try:
                with open(hist_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
                safe_lines = [l for l in lines if _is_safe_to_log(l)]
                commands = safe_lines[-MAX_COMMANDS:]
            except OSError:
                commands = []

    venv = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_DEFAULT_ENV")
    running = _find_shell_children(cwd)

    return TerminalSnapshot(
        working_directory=cwd,
        recent_commands=commands,
        active_venv=venv,
        running_processes=running,
    )
