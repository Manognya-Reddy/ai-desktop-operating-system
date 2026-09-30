import os
import shutil
import platform
import time

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "$Recycle.Bin", "System Volume Information"}
MAX_RESULTS = 20
MAX_DEPTH = 6


def default_search_roots():
    system = platform.system()
    roots = []
    if system == "Windows":
        home = os.path.expanduser("~")
        for folder in ["Desktop", "Documents", "Downloads"]:
            p = os.path.join(home, folder)
            if os.path.isdir(p):
                roots.append(p)
        for drive in ["C:\\", "D:\\"]:
            if os.path.isdir(drive):
                roots.append(drive)
    else:
        home = os.path.expanduser("~")
        roots.append(home)
    return roots


def find_files(keyword, roots=None, max_results=MAX_RESULTS):
    if roots is None:
        roots = default_search_roots()
    keyword = keyword.lower()
    matches = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        root_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
            if depth >= MAX_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            for name in filenames + dirnames:
                if keyword in name.lower():
                    matches.append(os.path.join(dirpath, name))
                    if len(matches) >= max_results:
                        return matches
    return matches


def disk_usage_summary():
    result = []
    if platform.system() == "Windows":
        import string
        drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    else:
        drives = ["/"]
    for d in drives:
        try:
            total, used, free = shutil.disk_usage(d)
            result.append({
                "drive": d,
                "total_gb": round(total / (1024 ** 3), 1),
                "used_gb": round(used / (1024 ** 3), 1),
                "free_gb": round(free / (1024 ** 3), 1),
            })
        except OSError:
            pass
    return result


def system_summary():
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
    }
    if HAS_PSUTIL:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        info["memory_used_percent"] = mem.percent
        info["memory_total_gb"] = round(mem.total / (1024 ** 3), 1)
        info["memory_available_gb"] = round(mem.available / (1024 ** 3), 1)
        info["battery_percent"] = None
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if battery:
            info["battery_percent"] = battery.percent
    return info


def top_processes(n=5):
    if not HAS_PSUTIL:
        return []
    procs = []
    for p in psutil.process_iter(["name", "memory_percent"]):
        try:
            procs.append((p.info["name"], p.info["memory_percent"] or 0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x[1], reverse=True)
    seen = set()
    top = []
    for name, mem in procs:
        if name in seen:
            continue
        seen.add(name)
        top.append((name, round(mem, 1)))
        if len(top) >= n:
            break
    return top


def open_path(path):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True, ""
    except Exception as e:
        return False, str(e)


def recent_downloads(n=10):
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if not os.path.isdir(downloads):
        return []
    files = []
    for name in os.listdir(downloads):
        full = os.path.join(downloads, name)
        if os.path.isfile(full):
            files.append((full, os.path.getmtime(full)))
    files.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in files[:n]]


def known_folder(name):
    home = os.path.expanduser("~")
    onedrive = os.path.join(home, "OneDrive")
    candidates = {
        "desktop": ["Desktop"],
        "documents": ["Documents"],
        "downloads": ["Downloads"],
        "pictures": ["Pictures"],
        "music": ["Music"],
        "videos": ["Videos"],
        "home": [""],
    }
    parts = candidates.get(name.lower())
    if parts is None:
        return None
    sub = parts[0]
    direct = os.path.join(home, sub) if sub else home
    if os.path.isdir(direct):
        return direct
    onedrive_path = os.path.join(onedrive, sub) if sub else onedrive
    if os.path.isdir(onedrive_path):
        return onedrive_path
    return direct


def list_directory(path, n=25):
    if not os.path.isdir(path):
        return None
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append({"name": name, "is_dir": os.path.isdir(full)})
    return entries[:n]


def code_user_dir():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, "Code", "User")
    home = os.path.expanduser("~")
    mac_path = os.path.join(home, "Library", "Application Support", "Code", "User")
    if os.path.isdir(mac_path):
        return mac_path
    return os.path.join(home, ".config", "Code", "User")


def folder_from_uri(uri):
    from urllib.parse import unquote
    if not uri or not uri.startswith("file:///"):
        return None
    local = unquote(uri[8:])
    if os.name != "nt":
        local = "/" + local
    return local


def detect_recent_vscode_folder():
    import json

    user_dir = code_user_dir()
    workspace_storage = os.path.join(user_dir, "workspaceStorage")
    if not os.path.isdir(workspace_storage):
        return None

    candidates = []
    for entry in os.listdir(workspace_storage):
        entry_path = os.path.join(workspace_storage, entry)
        meta_path = os.path.join(entry_path, "workspace.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        folder = folder_from_uri(meta.get("folder"))
        if not folder or not os.path.isdir(folder):
            continue

        touched = os.path.getmtime(meta_path)
        state_path = os.path.join(entry_path, "state.vscdb")
        if os.path.isfile(state_path):
            touched = max(touched, os.path.getmtime(state_path))

        candidates.append((touched, folder))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
