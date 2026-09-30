# Architecture

This document maps each implemented component to the research question and
the design constraints in the original spec.

## Research question

> Can automatically constructed semantic representations of a developer's
> cross-application workspace reduce the time and manual effort required to
> resume interrupted development tasks?

## Component → research role

| Component | File(s) | Role in the research question |
|---|---|---|
| Workspace Collector | `backend/app/services/workspace/{filesystem,git_context,chrome_context,terminal_context}.py` | Produces the raw cross-application signals that a Project Snapshot is built from. Each collector fails independently and gracefully — a missing signal degrades snapshot completeness rather than blocking the pipeline. |
| Project Detection | `backend/app/services/workspace/detection.py` | Deterministic, explainable scoring of whether a set of collected signals belongs to one project — supports H3 (combining signals) directly, since the score is a transparent weighted sum. |
| Project Snapshot | `backend/app/models/project.py` (`Snapshot` + child tables), `backend/app/services/snapshots/snapshot_service.py` | The core research artifact: a structured, persisted representation of "the project as a whole" rather than isolated file/app memories. |
| Semantic indexing | `backend/app/services/retrieval/embeddings.py` | Local `all-MiniLM-L6-v2` embedding of a generated project description — the mechanism under test in H1. |
| Per-file semantic memory | `backend/app/services/memory/memory_service.py`, `MemoryItem` table | Embeds every individual file and browser tab from every snapshot (not just the project as a whole), indexed with a real FAISS `IndexFlatIP` vector index so a vague query like "the resume I sent Microsoft" can be matched and opened by meaning without knowing the exact filename or project. |
| Background checkpointing | `backend/app/services/snapshots/scheduler.py` | A daemon thread that re-snapshots whichever project was last saved/resumed every `PCM_SNAPSHOT_INTERVAL` seconds, per spec section 18 — so state isn't lost between explicit "save" commands. |
| Keyword baseline | `backend/app/services/retrieval/keyword_search.py`, `experiments/baselines/keyword_baseline.py` | The comparison point for H1 (semantic vs keyword retrieval accuracy). |
| Hybrid retrieval | `backend/app/services/retrieval/hybrid.py` | Combines semantic + path + git + recency into one explainable, configurable ranking — the mechanism under test in H3, and what a user's natural-language query is actually matched against. |
| Intent extraction | `backend/app/services/retrieval/intent.py` | Turns a natural-language request into a clean query string; deliberately minimal (this is a workspace-restoration tool, not a chatbot). |
| Restoration engine | `backend/app/services/restoration/restoration_service.py` | Executes a Project Snapshot back into an open workspace — the mechanism under test in H2/H4 (restoration time, manual actions). |
| Safety gate | `backend/app/services/restoration/safety.py` | Ensures restoration never runs a destructive command unattended — a precondition for the system to be usable in a real study without risk. |
| Ablation toggles | `backend/app/config.py` (`SIGNAL_*` flags) | Lets every signal be independently disabled so H3 can be tested directly by comparing `full_pcm` against `no_git`, `no_browser`, etc. |
| Research logging | `RestorationLog` table, `POST /restore` | Structured, exportable record of each retrieval/restoration event for later analysis — never used to fabricate results. |

## Data flow (per spec section 5)

```
Developer works
       ↓
Workspace Collector  (filesystem.py, git_context.py, chrome_context.py, terminal_context.py)
       ↓
Project Detection    (detection.py — transparent scoring)
       ↓
Project Snapshot     (snapshot_service.create_snapshot)
       ↓
SQLite storage        (models/project.py)
       ↓
Semantic indexing      (embeddings.py, run at snapshot time)
       ↓
User returns later
       ↓
Natural-language request
       ↓
Intent extraction      (intent.py)
       ↓
Hybrid retrieval        (hybrid.py: semantic + path + git + recency)
       ↓
Restoration Preview     (restoration_service.build_plan)
       ↓
User confirmation
       ↓
Workspace Restoration    (restoration_service.execute_plan, safety.py gate)
```

## Why SQLite + comma-separated embeddings instead of a vector DB

The spec explicitly asks for CPU-only, no-GPU, single-laptop operation and
warns against over-engineering. With a benchmark in the tens (not millions)
of projects, a full table scan with numpy cosine similarity is fast enough
that adding FAISS would add complexity without a measurable benefit. The
`hybrid_search` function is the single place this would change if a future
experiment needs FAISS — nothing else in the codebase assumes the storage
format.

## Why CDP for Chrome tabs instead of reading browser files directly

Chrome's `Sessions`/`Current Tabs` files are an undocumented, versioned
binary format (SNSS) that is unreliable to parse and often stale relative
to the live browser state. The DevTools Protocol (`--remote-debugging-port`)
is Chrome's own supported local API for exactly this, and it never leaves
localhost.
