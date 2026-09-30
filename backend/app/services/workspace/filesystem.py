"""
Collects filesystem-level signals for a given project folder.

Kept deliberately simple: walk the folder (bounded depth, ignoring common
noise directories), return recently-modified files. No file content is
read or transmitted anywhere.
"""
import os
import time
from dataclasses import dataclass, field
from typing import List

IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".idea", ".vscode",
}
MAX_DEPTH = 4
RECENT_FILE_LIMIT = 15
RECENT_WINDOW_SECONDS = 60 * 60 * 24 * 3  # 3 days


@dataclass
class FileInfo:
    path: str
    last_modified: float
    size: int = 0


@dataclass
class FilesystemSnapshot:
    project_path: str
    recent_files: List[FileInfo] = field(default_factory=list)


def _walk(root: str, max_depth: int):
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in filenames:
            yield os.path.join(dirpath, f)


def collect_filesystem_context(project_path: str) -> FilesystemSnapshot:
    if not os.path.isdir(project_path):
        return FilesystemSnapshot(project_path=project_path)

    now = time.time()
    candidates: List[FileInfo] = []
    try:
        for fpath in _walk(project_path, MAX_DEPTH):
            try:
                mtime = os.path.getmtime(fpath)
                size = os.path.getsize(fpath)
            except OSError:
                continue
            if now - mtime <= RECENT_WINDOW_SECONDS:
                candidates.append(FileInfo(path=fpath, last_modified=mtime, size=size))
    except OSError:
        pass

    candidates.sort(key=lambda f: f.last_modified, reverse=True)
    return FilesystemSnapshot(
        project_path=project_path,
        recent_files=candidates[:RECENT_FILE_LIMIT],
    )
