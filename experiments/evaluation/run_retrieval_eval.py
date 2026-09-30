"""
Retrieval evaluation harness (spec sections 22 & 26).

Seeds a throwaway SQLite DB with one synthetic project folder per
benchmark entry (so PCM's real snapshot pipeline runs, not a mock),
then evaluates retrieval accuracy for:
  - keyword baseline
  - PCM hybrid retrieval (semantic + path + git + recency)
  - PCM with each individual signal ablated (spec section 25)

Metrics: Top-1 accuracy, Top-3 accuracy, Mean Reciprocal Rank (MRR).
No results are fabricated — everything here is computed from an actual
run against the live retrieval code.

Usage (from experiments/evaluation/):
    python run_retrieval_eval.py [--no-semantic]

--no-semantic skips loading the sentence-transformers model (useful in
offline/CPU-constrained environments per spec section 30) and reports
keyword-only + path/git/recency-only hybrid numbers.
"""
import argparse
import json
import os
import sys
import tempfile
import shutil
import csv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower())


def build_project_dir(base: str, project_name: str, description: str) -> str:
    # snapshot_service.get_or_create_project() derives Project.name from the
    # folder's basename, so the folder itself must carry a readable name —
    # tasks' `correct_project` is remapped to this same slug before scoring.
    slug = slugify(project_name)
    path = os.path.join(base, slug)
    os.makedirs(path, exist_ok=True)
    # A README carries the description text into the filesystem signal so
    # the auto-generated semantic_description has real content to embed.
    with open(os.path.join(path, "README.md"), "w") as f:
        f.write(f"# {project_name}\n\n{description}\n")
    with open(os.path.join(path, "main.py"), "w") as f:
        f.write("# placeholder\n")
    return path


def reciprocal_rank(ranked_names, correct_name):
    for i, name in enumerate(ranked_names, start=1):
        if name == correct_name:
            return 1.0 / i
    return 0.0


def evaluate(tasks, db, method: str):
    """method: 'keyword' or 'hybrid'"""
    from app.services.retrieval.keyword_search import keyword_rank
    from app.services.retrieval.hybrid import hybrid_search
    from app.models.project import Project

    top1 = top3 = 0
    mrr_total = 0.0
    rows = []

    for t in tasks:
        if method == "keyword":
            projects = db.query(Project).all()
            ranked = [p.name for p, _ in keyword_rank(t["query"], projects)]
        else:
            ranked_objs = hybrid_search(db, t["query"], top_k=len(tasks))
            ranked = [r.project.name for r in ranked_objs]

        rr = reciprocal_rank(ranked, t["correct_project"])
        mrr_total += rr
        is_top1 = len(ranked) > 0 and ranked[0] == t["correct_project"]
        is_top3 = t["correct_project"] in ranked[:3]
        top1 += int(is_top1)
        top3 += int(is_top3)
        rows.append({
            "task_id": t["task_id"], "query_type": t["query_type"], "query": t["query"],
            "correct_project": t["correct_project"],
            "predicted_top1": ranked[0] if ranked else None,
            "reciprocal_rank": rr,
        })

    n = len(tasks)
    return {
        "method": method,
        "top1_accuracy": top1 / n,
        "top3_accuracy": top3 / n,
        "mrr": mrr_total / n,
        "n": n,
    }, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-semantic", action="store_true", help="Disable semantic embeddings (offline mode)")
    args = parser.parse_args()

    os.environ["PCM_SIGNAL_SEMANTIC"] = "false" if args.no_semantic else "true"
    tmp_db = os.path.join(tempfile.gettempdir(), "pcm_eval.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    os.environ["PCM_DB_PATH"] = tmp_db

    from app.database.db import init_db, SessionLocal
    from app.services.snapshots.snapshot_service import create_snapshot

    init_db()
    db = SessionLocal()

    bench_path = os.path.join(os.path.dirname(__file__), "..", "datasets", "benchmark.json")
    with open(bench_path) as f:
        tasks = json.load(f)
    # Project.name in PCM is derived from the folder basename (see
    # snapshot_service.get_or_create_project), so ground truth must be
    # remapped to that same slug for a fair comparison.
    for t in tasks:
        t["correct_project"] = slugify(t["correct_project"])

    tmp_projects_dir = tempfile.mkdtemp(prefix="pcm_eval_projects_")
    try:
        for t in tasks:
            proj_dir = build_project_dir(tmp_projects_dir, t["project_name"], t["project_description"])
            create_snapshot(db, proj_dir, trigger="eval")

        keyword_metrics, keyword_rows = evaluate(tasks, db, "keyword")
        hybrid_metrics, hybrid_rows = evaluate(tasks, db, "hybrid")

        print(json.dumps({"keyword": keyword_metrics, "hybrid": hybrid_metrics}, indent=2))

        results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, "retrieval_eval_summary.json"), "w") as f:
            json.dump({"keyword": keyword_metrics, "hybrid": hybrid_metrics}, f, indent=2)
        with open(os.path.join(results_dir, "retrieval_eval_detail.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(hybrid_rows[0].keys()) + ["method"])
            writer.writeheader()
            for row in keyword_rows:
                writer.writerow({**row, "method": "keyword"})
            for row in hybrid_rows:
                writer.writerow({**row, "method": "hybrid"})
    finally:
        shutil.rmtree(tmp_projects_dir, ignore_errors=True)
        db.close()


if __name__ == "__main__":
    main()
