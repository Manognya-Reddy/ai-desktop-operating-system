import os
import numpy as np
import faiss
from app.models.project import MemoryItem
from app.services.retrieval.embeddings import embed_text, embedding_to_str, str_to_embedding
from app.config import settings


def index_snapshot(db, project, snapshot):
    if not settings.SIGNAL_SEMANTIC:
        return

    for f in snapshot.files:
        name = os.path.basename(f.path)
        parent = os.path.basename(os.path.dirname(f.path))
        text = f"file {name} in {parent}, part of project {project.name}"
        vec = embed_text(text)
        db.add(MemoryItem(
            project_id=project.id, snapshot_id=snapshot.id, kind="file",
            text=text, locator=f.path, embedding=embedding_to_str(vec),
        ))

    for t in snapshot.browser_tabs:
        title = t.title or t.url
        text = f"browser tab {title}, part of project {project.name}"
        vec = embed_text(text)
        db.add(MemoryItem(
            project_id=project.id, snapshot_id=snapshot.id, kind="tab",
            text=text, locator=t.url, embedding=embedding_to_str(vec),
        ))

    if snapshot.git_context and snapshot.git_context.last_commit_message:
        text = f"git commit {snapshot.git_context.last_commit_message}, part of project {project.name}"
        vec = embed_text(text)
        db.add(MemoryItem(
            project_id=project.id, snapshot_id=snapshot.id, kind="commit",
            text=text, locator=snapshot.git_context.repository_path or project.path,
            embedding=embedding_to_str(vec),
        ))

    db.commit()


def build_faiss_index(items):
    if not items:
        return None, []
    dim = len(str_to_embedding(items[0].embedding))
    index = faiss.IndexFlatIP(dim)
    vectors = np.stack([str_to_embedding(i.embedding) for i in items]).astype(np.float32)
    index.add(vectors)
    return index, items


def recall(db, query, top_k=5):
    if not settings.SIGNAL_SEMANTIC:
        return []

    items = db.query(MemoryItem).filter(MemoryItem.embedding.isnot(None)).all()
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
