"""Audit logging. Never write passwords, tokens or attachment contents here."""
import json
import logging

from sqlalchemy.orm import Session

from app.models import AuditLog

log = logging.getLogger("servicedesk.audit")


def audit(
    db: Session, action: str, *, actor_id: int | None = None, actor_label: str | None = None,
    entity_type: str | None = None, entity_id: str | int | None = None, detail: dict | str | None = None,
    ip: str | None = None, request_id: str | None = None, outcome: str = "success",
) -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail, default=str, ensure_ascii=False)
    if detail and len(detail) > 2000:
        detail = detail[:1997] + "..."
    db.add(AuditLog(
        actor_id=actor_id, actor_label=actor_label, action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None, detail=detail,
        ip_address=ip, request_id=request_id, outcome=outcome,
    ))
    log.info("audit action=%s actor=%s entity=%s:%s outcome=%s", action, actor_id, entity_type, entity_id, outcome)


def audit_p(db: Session, principal, action: str, **kw) -> None:
    """Convenience wrapper using a Principal."""
    audit(db, action, actor_id=principal.id, actor_label=principal.user.email, ip=principal.ip,
          request_id=principal.request_id, **kw)
