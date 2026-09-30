"""
Automatic Project Detection (spec section 9).

Deterministic, explainable scoring rather than ML: given the collected
workspace signals (folder, git repo path, terminal cwd, browser tabs),
decide whether they belong to the "current" project and produce a
transparent per-signal score. This is what gets logged for the research
paper / ablation experiments.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List

from app.services.workspace.filesystem import FilesystemSnapshot
from app.services.workspace.git_context import GitSnapshot
from app.services.workspace.terminal_context import TerminalSnapshot
from app.services.workspace.chrome_context import ChromeSnapshot


@dataclass
class DetectionResult:
    project_path: str
    score: float
    breakdown: Dict[str, float] = field(default_factory=dict)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def score_project_membership(
    project_path: str,
    fs: FilesystemSnapshot,
    git: GitSnapshot,
    terminal: TerminalSnapshot,
    chrome: ChromeSnapshot,
) -> DetectionResult:
    """
    Each signal contributes 0.0-1.0. Weighted sum matches the same
    weighting spirit as the hybrid retrieval ranking (kept independent so
    it's tunable separately in ablation experiments).
    """
    breakdown: Dict[str, float] = {}

    # Git repository match: does the detected repo live under project_path?
    if git.available and git.repository_path:
        breakdown["git_repository_match"] = (
            1.0 if _norm(git.repository_path).startswith(_norm(project_path)) else 0.0
        )
    else:
        breakdown["git_repository_match"] = 0.0

    # Folder match: fs signal was collected from this exact path.
    breakdown["folder_match"] = 1.0 if _norm(fs.project_path) == _norm(project_path) else 0.0

    # Terminal directory match: cwd is inside the project folder.
    breakdown["terminal_directory_match"] = (
        1.0 if _norm(terminal.working_directory).startswith(_norm(project_path)) else 0.0
    )

    # File overlap: nonzero recent files found under the folder.
    breakdown["file_overlap"] = min(len(fs.recent_files) / 5.0, 1.0)

    # Browser relevance: crude heuristic — project folder name appears in
    # any open tab title/url. Cheap and explainable; upgraded to semantic
    # similarity at the retrieval stage, not here.
    project_name = os.path.basename(project_path.rstrip(os.sep)).lower()
    browser_hits = sum(
        1 for t in chrome.tabs
        if project_name and (project_name in t.title.lower() or project_name in t.url.lower())
    )
    breakdown["browser_relevance"] = min(browser_hits / 2.0, 1.0)

    weights = {
        "git_repository_match": 0.30,
        "folder_match": 0.25,
        "terminal_directory_match": 0.20,
        "file_overlap": 0.15,
        "browser_relevance": 0.10,
    }
    score = sum(breakdown[k] * w for k, w in weights.items())

    return DetectionResult(project_path=project_path, score=score, breakdown=breakdown)
