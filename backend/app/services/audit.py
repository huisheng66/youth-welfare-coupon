from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def write_audit(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )
