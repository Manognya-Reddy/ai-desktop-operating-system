import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.models.project import Project, Snapshot, RestorationLog, MemoryItem
from app.schemas.schemas import (
    ProjectOut, SnapshotOut, SnapshotCreateRequest,
    SearchRequest, SearchResponse, SearchResultItem,
    RestoreRequest, RestoreResponse, RestorePlanItem,
    ChatRequest, ChatResponse,
)
from app.services.snapshots.snapshot_service import create_snapshot
from app.services.retrieval.hybrid import hybrid_search
from app.services.retrieval.intent import extract_intent
from app.services.restoration.restoration_service import build_plan, execute_plan
from app.services.chat.chat_service import handle_message

router = APIRouter()


@router.post("/snapshot", response_model=SnapshotOut)
def post_snapshot(req: SnapshotCreateRequest, db: Session = Depends(get_db)):
    snapshot = create_snapshot(db, req.project_path, trigger=req.trigger)
    return snapshot


@router.get("/projects", response_model=List[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.updated_at.desc()).all()


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/snapshots/{project_id}", response_model=List[SnapshotOut])
def get_snapshots(project_id: str, db: Session = Depends(get_db)):
    return (
        db.query(Snapshot)
        .filter(Snapshot.project_id == project_id)
        .order_by(Snapshot.created_at.desc())
        .all()
    )


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, db: Session = Depends(get_db)):
    intent = extract_intent(req.query)
    ranked = hybrid_search(db, intent.query, top_k=req.top_k)
    results = [
        SearchResultItem(
            project=ProjectOut.model_validate(r.project),
            score=r.score,
            rank=i + 1,
            breakdown=r.breakdown,
        )
        for i, r in enumerate(ranked)
    ]
    return SearchResponse(intent=intent.intent, query=intent.query, results=results)


@router.post("/restore", response_model=RestoreResponse)
def restore(req: RestoreRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if req.snapshot_id:
        snapshot = db.query(Snapshot).filter(Snapshot.id == req.snapshot_id).first()
    else:
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.project_id == project.id)
            .order_by(Snapshot.created_at.desc())
            .first()
        )
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshot available for this project")

    plan = build_plan(project.path, snapshot)

    start = time.time()
    executed, warnings, skipped = execute_plan(plan, confirm_unsafe=req.confirm_unsafe)
    elapsed = time.time() - start

    db.add(RestorationLog(
        query=None,
        retrieved_project_id=project.id,
        correct_project_id=None,
        similarity_score=None,
        retrieval_rank=None,
        restoration_components=",".join(executed),
        restoration_success=len(executed) > 0,
        time_taken_seconds=elapsed,
        manual_intervention=req.confirm_unsafe,
    ))
    db.commit()

    return RestoreResponse(
        project_id=project.id,
        plan=[RestorePlanItem(**item) for item in plan],
        executed=executed,
        warnings=warnings,
        skipped_unsafe=[RestorePlanItem(**item) for item in skipped],
    )


@router.delete("/data")
def delete_all_data(db: Session = Depends(get_db)):
    """Spec section 29 — 'Delete all stored data' privacy control."""
    db.query(RestorationLog).delete()
    db.query(MemoryItem).delete()
    db.query(Snapshot).delete()
    db.query(Project).delete()
    db.commit()
    return {"status": "deleted"}


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    result = handle_message(
        db, req.message, active_project_id=req.active_project_id,
        awaiting=req.awaiting, context=req.context, unlocked=req.unlocked,
    )
    return ChatResponse(
        reply=result.reply,
        active_project_id=result.active_project_id,
        active_project_path=result.active_project_path,
        awaiting=result.awaiting,
        data=result.data,
        unlocked=result.unlocked,
    )


@router.get("/system")
def system_status():
    from app.services.osassist import os_tools
    return {
        "system": os_tools.system_summary(),
        "disks": os_tools.disk_usage_summary(),
    }
