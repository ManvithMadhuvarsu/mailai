from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import GmailAccount, JobRun, User, UserPreference
from app.schemas import PreferenceUpdateRequest
from app.services.audit import audit


router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user.id).first()
    runs = (
        db.query(JobRun)
        .filter(JobRun.user_id == user.id)
        .order_by(JobRun.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "user": {"id": user.id, "email": user.email},
        "gmail_connected": bool(account),
        "preferences": {
            "mode": pref.mode if pref else "labels_only",
            "poll_interval_minutes": pref.poll_interval_minutes if pref else 180,
            "paused": pref.paused if pref else False,
        },
        "recent_runs": [
            {"id": r.id, "status": r.status, "summary": r.summary, "created_at": r.created_at.isoformat()}
            for r in runs
        ],
    }


@router.post("/preferences")
def update_preferences(
    payload: PreferenceUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.mode = payload.mode
    pref.poll_interval_minutes = payload.poll_interval_minutes
    pref.paused = payload.paused
    db.commit()
    audit(db, "preferences.updated", f"mode={payload.mode},paused={payload.paused}", user_id=user.id)
    return {"ok": True}

