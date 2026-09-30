"""
Standalone keyword baseline (spec section 24), independent of the live
FastAPI app's DB — operates directly on the benchmark JSON so it can be
compared against PCM's semantic/hybrid retrieval without needing a
running server.
"""
import json
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from app.services.retrieval.keyword_search import _tokenize  # reuse the same tokenizer


def rank_keyword(query: str, projects: list) -> list:
    q_tokens = _tokenize(query)
    scored = []
    for p in projects:
        corpus = f"{p['project_name']} {p['project_description']}"
        c_tokens = _tokenize(corpus)
        overlap = q_tokens & c_tokens
        score = len(overlap) / len(q_tokens) if q_tokens else 0.0
        scored.append((p["project_name"], score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


if __name__ == "__main__":
    bench_path = os.path.join(os.path.dirname(__file__), "..", "datasets", "benchmark.json")
    with open(bench_path) as f:
        tasks = json.load(f)

    projects = [{"project_name": t["project_name"], "project_description": t["project_description"]} for t in tasks]

    correct_top1 = 0
    for t in tasks:
        ranking = rank_keyword(t["query"], projects)
        top1 = ranking[0][0]
        if top1 == t["correct_project"]:
            correct_top1 += 1

    print(f"Keyword baseline top-1 accuracy: {correct_top1}/{len(tasks)} = {correct_top1/len(tasks):.2%}")
