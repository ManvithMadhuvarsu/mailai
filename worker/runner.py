"""
worker/runner.py

Simple DB-backed worker for multi-tenant mode.
This keeps legacy single-user runtime untouched while enabling queued user runs.
"""

import logging
import os
import time
from datetime import datetime

from app.bootstrap import init_db
from app.db import SessionLocal
from app.models import JobRun, UserPreference
from app.services.audit import audit
from app.services.tenant_runner import complete_run
from main import run


logger = logging.getLogger("worker.runner")


def _poll_seconds() -> int:
    return int(os.getenv("WORKER_POLL_SECONDS", "10"))


def loop():
    init_db()
    logger.info("Multi-tenant worker started.")
    while True:
        db = SessionLocal()
        try:
            queued = (
                db.query(JobRun)
                .filter(JobRun.status == "queued")
                .order_by(JobRun.created_at.asc())
                .first()
            )
            if not queued:
                time.sleep(_poll_seconds())
                continue

            pref = db.query(UserPreference).filter(UserPreference.user_id == queued.user_id).first()
            if pref and pref.paused:
                complete_run(db, queued, "failed", error="Agent is paused.")
                continue

            queued.status = "running"
            db.add(queued)
            db.commit()

            # Legacy runner call: this is intentionally retained for compatibility.
            # Next phase can pass full user context and per-user token handling.
            run()
            complete_run(db, queued, "success", summary="Completed run via legacy pipeline.")
            audit(db, "worker.run.success", f"job_run_id={queued.id}", user_id=queued.user_id)
        except Exception as e:
            logger.exception("Worker run failed")
            if "queued" in locals() and queued:
                complete_run(db, queued, "failed", error=str(e))
                audit(db, "worker.run.failed", str(e), user_id=queued.user_id)
        finally:
            db.close()
        time.sleep(1)


if __name__ == "__main__":
    loop()

