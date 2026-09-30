from dataclasses import dataclass, field
from typing import List, Optional

try:
    import git
    from git.exc import InvalidGitRepositoryError, NoSuchPathError
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False

MAX_DIFF_CHARS = 200000
MAX_UNTRACKED_FILE_CHARS = 20000
MAX_UNTRACKED_FILES = 15


@dataclass
class GitSnapshot:
    repository_path: Optional[str] = None
    branch: Optional[str] = None
    last_commit_hash: Optional[str] = None
    last_commit_message: Optional[str] = None
    modified_files: List[str] = field(default_factory=list)
    untracked_files: List[str] = field(default_factory=list)
    available: bool = False
    diff_patch: Optional[str] = None
    untracked_content: Optional[dict] = None


def collect_git_context(project_path):
    if not GIT_AVAILABLE:
        return GitSnapshot()

    try:
        repo = git.Repo(project_path, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return GitSnapshot()
    except Exception:
        return GitSnapshot()

    try:
        branch = repo.active_branch.name
    except Exception:
        branch = None

    try:
        last_commit = repo.head.commit
        commit_hash = last_commit.hexsha[:10]
        commit_msg = last_commit.message.strip().splitlines()[0] if last_commit.message else ""
    except Exception:
        commit_hash, commit_msg = None, None

    try:
        modified = [item.a_path for item in repo.index.diff(None)]
    except Exception:
        modified = []

    try:
        untracked = repo.untracked_files
    except Exception:
        untracked = []

    try:
        repo_path = repo.working_tree_dir
    except Exception:
        repo_path = project_path

    diff_patch = None
    try:
        if modified:
            raw_diff = repo.git.diff()
            if raw_diff:
                if not raw_diff.endswith("\n"):
                    raw_diff += "\n"
                diff_patch = raw_diff[:MAX_DIFF_CHARS]
    except Exception:
        diff_patch = None

    untracked_content = None
    try:
        if untracked:
            untracked_content = {}
            for rel_path in untracked[:MAX_UNTRACKED_FILES]:
                full_path = f"{repo_path}/{rel_path}"
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        untracked_content[rel_path] = f.read()[:MAX_UNTRACKED_FILE_CHARS]
                except OSError:
                    continue
    except Exception:
        untracked_content = None

    return GitSnapshot(
        repository_path=repo_path,
        branch=branch,
        last_commit_hash=commit_hash,
        last_commit_message=commit_msg,
        modified_files=list(modified),
        untracked_files=list(untracked),
        available=True,
        diff_patch=diff_patch,
        untracked_content=untracked_content,
    )
