# Research Documentation

## Hypotheses (spec section 27)

- **H1** — Semantic project retrieval improves project identification
  accuracy compared with keyword-based retrieval.
- **H2** — Project Snapshot-based restoration reduces workspace restoration
  time compared with manual restoration.
- **H3** — Combining multiple workspace signals improves project
  identification compared with individual signals.
- **H4** — PCM reduces the number of manual actions required to resume
  interrupted work.

## Metrics (spec section 26)

**Retrieval:** Top-1 accuracy, Top-3 accuracy, MRR, similarity/confidence
score — computed by `experiments/evaluation/run_retrieval_eval.py`.

**Restoration:** restoration time, restoration completeness, number of
manual actions — logged automatically to the `restoration_logs` table on
every `POST /restore` call and exportable as CSV/JSON.

**User study:** task completion time, perceived effort, satisfaction — not
automated; intended to be collected manually alongside real usage, per the
spec's instruction not to automate the human baseline.

## How to run the experiments already in this repo

```bash
cd experiments/datasets && python generate_benchmark.py
cd ../baselines && python keyword_baseline.py
cd ../evaluation && python run_retrieval_eval.py --no-semantic
cd ../evaluation && python run_ablation.py --no-semantic
```

Drop `--no-semantic` once `all-MiniLM-L6-v2` is cached locally (first run
needs one internet connection to download it) to get real semantic
similarity numbers instead of the keyword-only fallback.

## Result provenance

Every number in `experiments/results/` was produced by actually running the
scripts above against a temporary SQLite database seeded with the 25-task
`benchmark.json`, using the real `hybrid_search` / `keyword_rank` code paths
— not hand-written or estimated. Example from a real `--no-semantic` run in
this repo's dev environment:

```
keyword: top1_accuracy=0.68  top3_accuracy=0.80  mrr=0.746
hybrid:  top1_accuracy=0.64  top3_accuracy=0.80  mrr=0.735
```

With semantic embeddings disabled, `hybrid` is expected to perform close to
(or slightly below) `keyword`, since its semantic term is zeroed and it's
only gaining a small amount from the path/git/recency terms — this is the
correct, expected ablation behavior, not a bug. **These specific numbers are
a debug/example run of a synthetic offline benchmark and must not be quoted
as a research result** — re-run the full pipeline (with semantic embeddings
enabled, and ideally against real developer workspaces rather than the
synthetic benchmark) before citing any number in a paper.

## Extending the benchmark

`experiments/datasets/generate_benchmark.py` currently generates 25
synthetic tasks across five query types (exact, paraphrased, vague,
contextual, ambiguous). For a real study, replace or extend `PROJECTS` with
tasks drawn from actual developer workflows, and consider having multiple
annotators write the natural-language queries independently to avoid
templating artifacts (the current templates are intentionally simple
placeholders, not validated query data).
