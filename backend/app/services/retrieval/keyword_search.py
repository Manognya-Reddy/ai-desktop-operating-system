"""
Simple keyword baseline used for comparison against semantic retrieval
(spec sections 12/24/H1). Tokenize -> overlap score against project
name + description.
"""
import re
from typing import List
from app.models.project import Project

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set:
    return set(_TOKEN_RE.findall((text or "").lower()))


def keyword_score(query: str, project: Project) -> float:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0
    corpus = f"{project.name} {project.semantic_description or ''}"
    corpus_tokens = _tokenize(corpus)
    if not corpus_tokens:
        return 0.0
    overlap = query_tokens & corpus_tokens
    return len(overlap) / len(query_tokens)


def keyword_rank(query: str, projects: List[Project]) -> List[tuple]:
    scored = [(p, keyword_score(query, p)) for p in projects]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
