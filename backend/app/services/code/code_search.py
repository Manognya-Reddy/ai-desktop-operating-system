import os
import re

CODE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go")
MAX_SYMBOLS_PER_FILE = 40
MAX_FILE_BYTES = 300000

PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
PY_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[:\(]")
JS_FUNC_RE = re.compile(r"(?:function\s+(\w+)\s*\(|const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*?\)?\s*=>|(\w+)\s*\([^)]*\)\s*\{)")


def extract_symbols(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in CODE_EXTENSIONS:
        return []
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    symbols = []
    if ext == ".py":
        for line in lines:
            m = PY_DEF_RE.match(line)
            if m:
                symbols.append(("function", m.group(1)))
            m = PY_CLASS_RE.match(line)
            if m:
                symbols.append(("class", m.group(1)))
    else:
        for line in lines:
            m = JS_FUNC_RE.search(line)
            if m:
                name = m.group(1) or m.group(2) or m.group(3)
                if name and name not in ("if", "for", "while", "switch", "catch"):
                    symbols.append(("function", name))

    return symbols[:MAX_SYMBOLS_PER_FILE]


def index_code_symbols(db, project, snapshot):
    from app.models.project import MemoryItem
    from app.services.retrieval.embeddings import embed_text, embedding_to_str
    from app.config import settings

    if not settings.SIGNAL_SEMANTIC:
        return

    for f in snapshot.files:
        symbols = extract_symbols(f.path)
        for kind, name in symbols:
            text = f"{kind} {name} in {os.path.basename(f.path)}, part of project {project.name}"
            vec = embed_text(text)
            db.add(MemoryItem(
                project_id=project.id, snapshot_id=snapshot.id, kind="symbol",
                text=text, locator=f"{f.path}::{name}", embedding=embedding_to_str(vec),
            ))
    db.commit()


def search_code(db, query, top_k=5):
    from app.models.project import MemoryItem
    from app.services.memory.memory_service import build_faiss_index
    from app.services.retrieval.embeddings import embed_text
    from app.config import settings
    import numpy as np

    if not settings.SIGNAL_SEMANTIC:
        return []

    items = db.query(MemoryItem).filter(MemoryItem.kind == "symbol", MemoryItem.embedding.isnot(None)).all()
    if not items:
        return []

    index, item_list = build_faiss_index(items)
    if index is None:
        return []

    q_vec = embed_text(query).astype(np.float32).reshape(1, -1)
    scores, positions = index.search(q_vec, min(top_k, len(item_list)))

    results = []
    for score, pos in zip(scores[0], positions[0]):
        if pos == -1:
            continue
        results.append((item_list[pos], float(score)))
    return results
