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
    """The user's public IP address.

    On Vercel every request passes through Vercel's edge, which puts the visitor's real address in
    x-vercel-forwarded-for / x-real-ip (Vercel overwrites these, so users cannot fake them). On your own server
    behind Nginx/IIS, run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy ip>; on the office network
    without a proxy this is the PC's own LAN address.
    """
    import os
    if os.environ.get("VERCEL"):
        for h in ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"):
            v = request.headers.get(h)
            if v:
                return v.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


PRINCIPAL_TTL = 60   # seconds; role changes made in the app clear it at once


def access_for(db: Session, user_id: int):
    """(role codes, permission codes, group ids, lead group ids) — 2 small queries, cached briefly per instance."""
    from app.core.cache import cached
    from app.models import Permission, Role, RolePermission, UserRole

    def load():
        rows = db.execute(select(Role.code, Permission.code).select_from(UserRole)
                          .join(Role, Role.id == UserRole.role_id)
                          .outerjoin(RolePermission, RolePermission.role_id == Role.id)
                          .outerjoin(Permission, Permission.id == RolePermission.permission_id)
                          .where(UserRole.user_id == user_id)).all()
        mem = db.execute(select(SupportGroupMember.group_id, SupportGroupMember.is_lead)
                         .where(SupportGroupMember.user_id == user_id)).all()
        return (frozenset(r for r, _ in rows), frozenset(p for _, p in rows if p),
                frozenset(m.group_id for m in mem), frozenset(m.group_id for m in mem if m.is_lead))
    return cached(("principal", user_id), PRINCIPAL_TTL, load)


def forget_access(user_id: int | None = None) -> None:
    from app.core.cache import forget, forget_key
    if user_id is None:
        forget("principal")
    else:
        forget_key(("principal", user_id))


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

    roles, perms, groups, leads = access_for(db, user.id)
    return Principal(
        user=user,
        permissions=perms,
        roles=roles,
        group_ids=groups,
        lead_group_ids=leads,
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
