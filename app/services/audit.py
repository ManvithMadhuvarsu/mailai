from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, action: str, details: str = "", user_id: int | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, details=details))
    db.commit()

