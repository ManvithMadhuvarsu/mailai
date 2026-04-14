from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import JobRun, User, UserPreference
from app.services.audit import audit
from app.services.tenant_runner import enqueue_user_run


router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/pause")
def pause_agent(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.paused = True
    db.commit()
    audit(db, "agent.paused", user_id=user.id)
    return {"ok": True}


@router.post("/resume")
def resume_agent(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.paused = False
    db.commit()
    run = enqueue_user_run(db, user.id)
    audit(db, "agent.resumed", user_id=user.id)
    return {"ok": True, "job_run_id": run.id}


@router.get("/activity")
def activity(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(JobRun)
        .filter(JobRun.user_id == user.id)
        .order_by(JobRun.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "summary": r.summary,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
    }

