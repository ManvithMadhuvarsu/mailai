from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import AuditLog, GmailAccount, JobRun, ProcessedMessage, User, UserPreference
from app.services.audit import audit


router = APIRouter(tags=["compliance"])


@router.get("/privacy", response_class=HTMLResponse)
def privacy():
    return """
    <h2>Privacy Policy</h2>
    <p>MailAI processes Gmail metadata/content only for user-authorized automation.</p>
    <p>Users can disconnect and request data deletion at any time.</p>
    """


@router.get("/terms", response_class=HTMLResponse)
def terms():
    return """
    <h2>Terms of Service</h2>
    <p>MailAI is provided as-is. Users are responsible for reviewing drafts before sending.</p>
    """


@router.post("/data/delete")
def delete_my_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(GmailAccount).filter(GmailAccount.user_id == user.id).delete()
    db.query(UserPreference).filter(UserPreference.user_id == user.id).delete()
    db.query(JobRun).filter(JobRun.user_id == user.id).delete()
    db.query(ProcessedMessage).filter(ProcessedMessage.user_id == user.id).delete()
    db.query(AuditLog).filter(AuditLog.user_id == user.id).delete()
    user.is_active = False
    db.add(user)
    db.commit()
    audit(db, "data.delete.requested", user_id=user.id)
    return {"ok": True, "message": "User data scheduled/deleted and account disabled."}

