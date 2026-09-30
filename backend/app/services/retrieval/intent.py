"""
Minimal intent extraction for the restoration search box. This is a
workspace-restoration system, not a general chatbot (spec section 14),
so the only intent it needs is `restore_project` plus a cleaned query
string. Works entirely offline; an optional LLM path exists only for
projects that explicitly want smarter query cleanup and is never
required for the system to function (spec section 34).
"""
import re
from dataclasses import dataclass

_FILLER_PATTERNS = [
    r"^continue\s+(my|the)?\s*",
    r"^open\s+(my|the)?\s*",
    r"^resume\s+(my|the)?\s*",
    r"^go back to\s+(my|the)?\s*",
    r"\s+project$",
    r"\s+i was working on( yesterday| earlier| last week)?$",
]


@dataclass
class Intent:
    intent: str
    query: str


def extract_intent(raw_text: str) -> Intent:
    text = raw_text.strip()
    cleaned = text.lower()
    for pattern in _FILLER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = text.lower()
    return Intent(intent="restore_project", query=cleaned)
