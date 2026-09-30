import os
import platform
import subprocess

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "ms-settings:",
    "word": "winword.exe",
    "excel": "excel.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "spotify": "spotify.exe",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
}


def resolve_app_target(name):
    key = name.strip().lower()
    return APP_ALIASES.get(key, name.strip())


def launch_app(name):
    target = resolve_app_target(name)
    try:
        if platform.system() == "Windows":
            os.startfile(target)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            subprocess.Popen([target])
        return True, ""
    except Exception as e:
        return False, str(e)


def find_matching_processes(name):
    if not HAS_PSUTIL:
        return []
    key = name.strip().lower()
    matches = []
    for p in psutil.process_iter(["name"]):
        try:
            pname = (p.info.get("name") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if key in pname or pname.replace(".exe", "") == key:
            matches.append(p)
    return matches


def close_app(name):
    matches = find_matching_processes(name)
    if not matches:
        return False, f"No running process matching \"{name}\" found."
    closed = []
    for p in matches:
        try:
            p.terminate()
            closed.append(p.info.get("name") or str(p.pid))
        except Exception:
            continue
    if not closed:
        return False, "Found matching processes but couldn't close them."
    return True, ", ".join(set(closed))


def lock_screen():
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return True, ""
        return False, "Screen locking is only wired up for Windows right now."
    except Exception as e:
        return False, str(e)


def take_screenshot():
    try:
        from PIL import ImageGrab
        import time
        home = os.path.expanduser("~")
        folder = os.path.join(home, "Pictures", "PCM_Screenshots")
        os.makedirs(folder, exist_ok=True)
        filename = f"screenshot_{int(time.time())}.png"
        path = os.path.join(folder, filename)
        img = ImageGrab.grab()
        img.save(path)
        return True, path
    except Exception as e:
        return False, str(e)


def make_folder(path):
    try:
        os.makedirs(path, exist_ok=False)
        return True, ""
    except FileExistsError:
        return False, "That folder already exists."
    except Exception as e:
        return False, str(e)


def delete_path(path):
    try:
        if not os.path.exists(path):
            return False, "That path doesn't exist."
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True, ""
    except Exception as e:
        return False, str(e)


def empty_recycle_bin():
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0001 | 0x0002 | 0x0004)
            return True, ""
        return False, "Emptying the recycle bin is only wired up for Windows right now."
    except Exception as e:
        return False, str(e)
