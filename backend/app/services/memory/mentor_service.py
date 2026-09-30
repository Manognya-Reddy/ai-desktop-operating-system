import os

AUTH_HINTS = ("auth", "login", "session", "token")
TEST_HINTS = ("test", "spec")
DOC_FILES = ("readme.md", "readme.txt", "readme")


def touched_paths(snapshot):
    return [f.path for f in snapshot.files]


def check_auth_without_tests(snapshot):
    paths = touched_paths(snapshot)
    names = [os.path.basename(p).lower() for p in paths]

    touched_auth = any(any(h in n for h in AUTH_HINTS) for n in names)
    touched_tests = any(any(h in n for h in TEST_HINTS) for n in names)

    if touched_auth and not touched_tests:
        return "You modified an authentication-related file but I don't see a test file touched in this save."
    return None


def check_readme_not_updated(snapshot, project_path):
    readme_path = None
    for name in os.listdir(project_path) if os.path.isdir(project_path) else []:
        if name.lower() in DOC_FILES:
            readme_path = os.path.join(project_path, name)
            break
    if not readme_path:
        return None

    paths = touched_paths(snapshot)
    code_files_touched = [p for p in paths if os.path.splitext(p)[1] in (".py", ".js", ".ts")]
    readme_touched = any(os.path.normcase(p) == os.path.normcase(readme_path) for p in paths)

    if len(code_files_touched) >= 3 and not readme_touched:
        return "You changed several code files but your README wasn't touched in this save — might be worth a documentation update."
    return None


def check_carried_over_uncommitted(current_git, previous_git):
    if not current_git or not previous_git:
        return None
    current_modified = set((current_git.modified_files or "").split("\n")) - {""}
    previous_modified = set((previous_git.modified_files or "").split("\n")) - {""}
    carried = current_modified & previous_modified
    if carried:
        count = len(carried)
        noun = "file" if count == 1 else "files"
        return f"There are {count} uncommitted {noun} still carried over from your previous session."
    return None


def build_mentor_notes(project, snapshot, previous_snapshot):
    notes = []

    note = check_auth_without_tests(snapshot)
    if note:
        notes.append(note)

    note = check_readme_not_updated(snapshot, project.path)
    if note:
        notes.append(note)

    if previous_snapshot:
        note = check_carried_over_uncommitted(snapshot.git_context, previous_snapshot.git_context)
        if note:
            notes.append(note)

    return notes[:3]
