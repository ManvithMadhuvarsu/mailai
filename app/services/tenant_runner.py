from datetime import datetime

from sqlalchemy.orm import Session

from app.models import JobRun
from app.services.audit import audit


def enqueue_user_run(db: Session, user_id: int) -> JobRun:
    run = JobRun(user_id=user_id, status="queued", summary="Queued from API")
    db.add(run)
    db.commit()
    db.refresh(run)
    audit(db, "agent.enqueue", f"job_run_id={run.id}", user_id=user_id)
    return run


def complete_run(db: Session, run: JobRun, status: str, summary: str = "", error: str = "") -> None:
    run.status = status
    run.summary = summary
    run.error = error
    run.finished_at = datetime.utcnow()
    db.add(run)
    db.commit()

