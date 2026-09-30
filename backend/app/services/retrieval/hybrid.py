"""
Hybrid project retrieval: combines semantic similarity, keyword overlap
used as the "path/name relevance" term, git relevance, and recent-activity
recency into one explainable ranking function (spec section 13):

    final_score = w_semantic * semantic_similarity
                + w_path     * path_relevance
                + w_git      * git_relevance
                + w_recent   * recent_activity

Every term can be individually disabled via app.config.settings for
ablation experiments (spec section 25). Weights are also configurable.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models.project import Project
from app.services.retrieval.embeddings import embed_text, str_to_embedding, cosine_similarity
from app.services.retrieval.keyword_search import keyword_score


@dataclass
class RankedProject:
    project: Project
    score: float
    breakdown: Dict[str, float]


def _recent_activity_score(project: Project) -> float:
    if not project.updated_at:
        return 0.0
    updated = project.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600.0
    # Full score if touched within the last hour, decaying to 0 over 7 days.
    return max(0.0, 1.0 - (age_hours / (24 * 7)))


def _git_relevance_score(project: Project, query: str) -> float:
    # Cheap proxy: does the query mention a token resembling the project's
    # git branch history? We don't have live git state per-query here, so
    # fall back to name-token overlap as the closest available signal
    # without re-scanning disk on every search.
    return keyword_score(query, project) if project.semantic_description else 0.0


def hybrid_search(db: Session, query: str, top_k: int = 3) -> List[RankedProject]:
    projects: List[Project] = db.query(Project).all()
    if not projects:
        return []

    query_vec = embed_text(query) if settings.SIGNAL_SEMANTIC else None

    ranked: List[RankedProject] = []
    for p in projects:
        breakdown: Dict[str, float] = {}

        if settings.SIGNAL_SEMANTIC and query_vec is not None and p.embedding:
            breakdown["semantic_similarity"] = cosine_similarity(query_vec, str_to_embedding(p.embedding))
        else:
            breakdown["semantic_similarity"] = 0.0

        breakdown["path_relevance"] = keyword_score(query, p) if settings.SIGNAL_FILES else 0.0
        breakdown["git_relevance"] = _git_relevance_score(p, query) if settings.SIGNAL_GIT else 0.0
        breakdown["recent_activity"] = _recent_activity_score(p) if settings.SIGNAL_RECENT_ACTIVITY else 0.0

        score = (
            settings.WEIGHT_SEMANTIC * breakdown["semantic_similarity"]
            + settings.WEIGHT_PATH * breakdown["path_relevance"]
            + settings.WEIGHT_GIT * breakdown["git_relevance"]
            + settings.WEIGHT_RECENT * breakdown["recent_activity"]
        )

        ranked.append(RankedProject(project=p, score=score, breakdown=breakdown))

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:top_k]
