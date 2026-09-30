import os
import platform
import subprocess
from typing import List, Tuple

from app.models.project import Snapshot
from app.services.restoration.safety import classify_command


def build_plan(project_path: str, snapshot: Snapshot) -> List[dict]:
    plan: List[dict] = []

    plan.append({
        "component": "vscode",
        "description": f"Open VS Code at {project_path}",
        "safe": True,
        "action": {"type": "open_vscode", "path": project_path},
    })

    open_files = [f.path for f in snapshot.files][:10]
    if open_files:
        plan.append({
            "component": "files",
            "description": f"Open {len(open_files)} recent file(s)",
            "safe": True,
            "action": {"type": "open_files", "paths": open_files},
        })

    if snapshot.git_context and snapshot.git_context.branch:
        plan.append({
            "component": "git",
            "description": f"Checkout branch: {snapshot.git_context.branch}",
            "safe": True,
            "action": {
                "type": "git_checkout",
                "repo": snapshot.git_context.repository_path,
                "branch": snapshot.git_context.branch,
            },
        })

    has_diff = snapshot.git_context and snapshot.git_context.diff_patch
    has_untracked = snapshot.git_context and snapshot.git_context.untracked_content
    if has_diff or has_untracked:
        plan.append({
            "component": "git_working_tree",
            "description": "Restore uncommitted changes and untracked files",
            "safe": False,
            "action": {
                "type": "restore_working_tree",
                "repo": snapshot.git_context.repository_path,
                "diff_patch": snapshot.git_context.diff_patch,
                "untracked_content": snapshot.git_context.untracked_content,
            },
        })

    tabs = [t.url for t in snapshot.browser_tabs][:15]
    if tabs:
        plan.append({
            "component": "chrome",
            "description": f"Open {len(tabs)} Chrome tab(s)",
            "safe": True,
            "action": {"type": "open_tabs", "urls": tabs},
        })

    if snapshot.terminal_context and snapshot.terminal_context.working_directory:
        plan.append({
            "component": "terminal",
            "description": f"Open terminal at {snapshot.terminal_context.working_directory}",
            "safe": True,
            "action": {
                "type": "open_terminal",
                "cwd": snapshot.terminal_context.working_directory,
                "venv": snapshot.terminal_context.active_venv,
            },
        })

        commands = [c for c in (snapshot.terminal_context.recent_commands or "").split("\n") if c.strip()]
        if commands:
            last_cmd = commands[-1]
            classification = classify_command(last_cmd)
            if classification != "blocked":
                plan.append({
                    "component": "terminal_command",
                    "description": f"Run last command: {last_cmd}",
                    "safe": classification == "safe",
                    "action": {"type": "run_command", "command": last_cmd, "cwd": snapshot.terminal_context.working_directory},
                })

    return plan


def _open_vscode(path: str) -> Tuple[bool, str]:
    try:
        subprocess.Popen(["code", path], shell=(platform.system() == "Windows"))
        return True, ""
    except (FileNotFoundError, OSError) as e:
        return False, f"VS Code not found or failed to launch: {e}"


def _open_files(paths: List[str]) -> Tuple[bool, str]:
    missing = [p for p in paths if not os.path.exists(p)]
    existing = [p for p in paths if os.path.exists(p)]
    if not existing:
        return False, "None of the recorded files still exist."
    try:
        subprocess.Popen(["code", *existing], shell=(platform.system() == "Windows"))
    except (FileNotFoundError, OSError) as e:
        return False, f"Could not open files in VS Code: {e}"
    if missing:
        return True, f"{len(missing)} file(s) no longer exist and were skipped."
    return True, ""


def _open_terminal(cwd, venv=None):
    if not os.path.isdir(cwd):
        return False, f"Directory no longer exists: {cwd}"
    try:
        if platform.system() == "Windows":
            if venv and os.path.isdir(venv):
                activate = os.path.join(venv, "Scripts", "activate.bat")
                subprocess.Popen(["cmd.exe", "/K", f"cd /d {cwd} && call {activate}"])
            else:
                subprocess.Popen(["cmd.exe", "/K", f"cd /d {cwd}"])
        else:
            subprocess.Popen(["x-terminal-emulator"], cwd=cwd)
        return True, ""
    except (FileNotFoundError, OSError) as e:
        return False, f"Could not open terminal: {e}"


def _open_tabs(urls: List[str]) -> Tuple[bool, str]:
    try:
        import webbrowser
        for url in urls:
            webbrowser.open_new_tab(url)
        return True, ""
    except Exception as e:
        return False, f"Could not open browser tabs: {e}"


def _git_checkout(repo: str, branch: str) -> Tuple[bool, str]:
    try:
        import git
        r = git.Repo(repo)
        r.git.checkout(branch)
        return True, ""
    except Exception as e:
        return False, f"Git checkout failed: {e}"


def _restore_working_tree(repo, diff_patch, untracked_content):
    if not repo or not os.path.isdir(repo):
        return False, "Repository folder no longer exists."

    applied = []
    failed = []

    if diff_patch:
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False, encoding="utf-8") as f:
                f.write(diff_patch)
                patch_path = f.name
            result = subprocess.run(
                ["git", "-C", repo, "apply", "--whitespace=nowarn", patch_path],
                capture_output=True, text=True,
            )
            os.unlink(patch_path)
            if result.returncode == 0:
                applied.append("uncommitted changes")
            else:
                failed.append(f"diff didn't apply cleanly: {result.stderr.strip()[:200]}")
        except Exception as e:
            failed.append(f"diff apply failed: {e}")

    if untracked_content:
        import json
        try:
            content_map = json.loads(untracked_content) if isinstance(untracked_content, str) else untracked_content
        except Exception:
            content_map = {}
        written = 0
        for rel_path, text in content_map.items():
            full_path = os.path.join(repo, rel_path)
            if os.path.exists(full_path):
                continue
            try:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(text)
                written += 1
            except OSError:
                continue
        if written:
            applied.append(f"{written} untracked file(s)")

    if not applied and not failed:
        return True, "nothing to restore"
    if failed and not applied:
        return False, "; ".join(failed)
    msg = "restored " + ", ".join(applied)
    if failed:
        msg += " (" + "; ".join(failed) + ")"
    return True, msg


def _run_command(command: str, cwd: str) -> Tuple[bool, str]:
    try:
        subprocess.Popen(command, cwd=cwd, shell=True)
        return True, ""
    except Exception as e:
        return False, f"Command failed to launch: {e}"


EXECUTORS = {
    "open_vscode": lambda a: _open_vscode(a["path"]),
    "open_files": lambda a: _open_files(a["paths"]),
    "open_terminal": lambda a: _open_terminal(a["cwd"], a.get("venv")),
    "open_tabs": lambda a: _open_tabs(a["urls"]),
    "git_checkout": lambda a: _git_checkout(a["repo"], a["branch"]),
    "run_command": lambda a: _run_command(a["command"], a["cwd"]),
    "restore_working_tree": lambda a: _restore_working_tree(a["repo"], a["diff_patch"], a["untracked_content"]),
}


def execute_plan(plan: List[dict], confirm_unsafe: bool) -> Tuple[List[str], List[str], List[dict]]:
    """Returns (executed_component_names, warnings, skipped_unsafe_items)."""
    executed: List[str] = []
    warnings: List[str] = []
    skipped: List[dict] = []

    for item in plan:
        if not item["safe"] and not confirm_unsafe:
            skipped.append(item)
            continue

        executor = EXECUTORS.get(item["action"]["type"])
        if executor is None:
            warnings.append(f"No executor for component: {item['component']}")
            continue

        try:
            ok, msg = executor(item["action"])
        except Exception as e:  # a single failing component must not abort the rest
            ok, msg = False, str(e)

        if ok:
            executed.append(item["component"])
            if msg:
                warnings.append(f"{item['component']}: {msg}")
        else:
            warnings.append(f"{item['component']} could not be restored: {msg}")

    return executed, warnings, skipped
