"""
Safety gate for restoration (spec section 17). Nothing that executes a
shell command is ever run automatically — commands are only ever
*proposed*, and execution requires an explicit confirmation flag from the
caller (mirrored by confirm_unsafe in RestoreRequest / the "Restore
Everything" button in the UI).
"""
import re

DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdel\s+/f\b",
    r"\brd\s+/s\b",
    r"\bformat\s",
    r"\bmkfs\b",
    r"\bdrop\s+database\b",
    r"\bshutdown\b",
]


def is_dangerous_command(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(re.search(p, lowered) for p in DANGEROUS_PATTERNS)


def classify_command(cmd: str) -> str:
    """Returns 'blocked', 'needs_confirmation', or 'safe'."""
    if is_dangerous_command(cmd):
        return "blocked"
    # Anything that runs a program (not just `cd`) needs explicit confirmation.
    if cmd.strip() and not cmd.strip().lower().startswith("cd "):
        return "needs_confirmation"
    return "safe"
