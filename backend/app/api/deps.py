"""Request-scoped dependencies: DB session, authenticated principal, permission guards."""
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.models import SupportGroupMember, User


@dataclass
class Principal:
    user: User
    permissions: set[str]
    roles: set[str]
    group_ids: set[int] = field(default_factory=set)
    lead_group_ids: set[int] = field(default_factory=set)
    ip: str | None = None
    request_id: str | None = None

    @property
    def id(self) -> int:
        return self.user.id

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    @property
    def is_staff(self) -> bool:
        return "ticket.work" in self.permissions


def client_ip(request: Request) -> str | None:
    # Behind a reverse proxy, run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy ip>
    return request.client.host if request.client else None


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Authentication required.")
    try:
        payload = decode_access_token(auth[7:].strip())
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Session expired.", code="token_expired")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid credentials.")

    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise Unauthorized("Account is not active.")

    memberships = db.execute(
        select(SupportGroupMember.group_id, SupportGroupMember.is_lead).where(SupportGroupMember.user_id == user.id)
    ).all()
    return Principal(
        user=user,
        permissions=user.permission_codes,
        roles=user.role_codes,
        group_ids={m.group_id for m in memberships},
        lead_group_ids={m.group_id for m in memberships if m.is_lead},
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )


def require(*perms: str):
    """Dependency factory: principal must hold ALL listed permissions."""

    def _guard(principal: Principal = Depends(get_principal)) -> Principal:
        missing = [p for p in perms if not principal.can(p)]
        if missing:
            raise Forbidden("You do not have permission to perform this action.")
        return principal

    return _guard


def require_any(*perms: str):
    def _guard(principal: Principal = Depends(get_principal)) -> Principal:
        if not any(principal.can(p) for p in perms):
            raise Forbidden("You do not have permission to perform this action.")
        return principal

    return _guard
