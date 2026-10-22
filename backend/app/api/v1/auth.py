import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, get_principal
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import BusinessRuleError, Forbidden, TooManyRequests, Unauthorized
from app.core.rate_limit import login_limiter
from app.core.security import (
    check_user_password, create_access_token, hash_password, hash_token, needs_rehash, new_refresh_token,
    set_user_password, validate_password_strength, verify_password,
)
from app.models import RefreshToken, User, utcnow
from app.schemas.common import StrictIn
from app.services.audit import audit, audit_p

router = APIRouter(prefix="/auth", tags=["Authentication"])
REFRESH_COOKIE = "sd_refresh"
COOKIE_PATH = "/api/v1/auth"


class LoginIn(StrictIn):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(StrictIn):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    id: int
    full_name: str
    email: str
    employee_code: str
    job_title: str | None
    department: str | None
    location: str | None
    timezone: str
    roles: list[str]
    permissions: list[str]
    support_group_ids: list[int]
    lead_group_ids: list[int]


def _require_csrf_header(request: Request) -> None:
    # Cookie-authenticated endpoints require a custom header that cross-site forms cannot set.
    if request.headers.get("X-Requested-With") != "fetch":
        raise Forbidden("Missing anti-CSRF header.")


def _set_refresh_cookie(resp: Response, raw: str) -> None:
    s = get_settings()
    resp.set_cookie(REFRESH_COOKIE, raw, max_age=s.refresh_token_days * 86400, httponly=True,
                    secure=s.cookie_secure, samesite="strict", path=COOKIE_PATH)


def _issue(db: Session, user: User, resp: Response, request: Request, family: str | None = None) -> TokenOut:
    raw, digest = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=digest, family_id=family or str(uuid.uuid4()),
                        expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days),
                        user_agent=(request.headers.get("user-agent") or "")[:255]))
    _set_refresh_cookie(resp, raw)
    token, ttl = create_access_token(user.id)
    return TokenOut(access_token=token, expires_in=ttl)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_csrf_header(request)
    s = get_settings()
    ip = client_ip(request) or "unknown"
    if not login_limiter.allow(f"login:{ip}", s.login_rate_limit_per_minute):
        raise TooManyRequests("Too many sign-in attempts. Please wait a minute and try again.")

    email = data.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()
    generic = Unauthorized("Incorrect email or password.", code="invalid_credentials")

    if user and user.locked_until and user.locked_until > now:
        verify_password(data.password, None)  # equalise timing
        audit(db, "auth.login", actor_id=user.id, actor_label=email, ip=ip, outcome="locked")
        db.commit()
        raise Unauthorized("Account temporarily locked after repeated failures. Try again later.",
                           code="account_locked")

    ok = check_user_password(user, data.password)
    if not user or not ok or not user.is_active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= s.max_failed_logins:
                user.locked_until = now + timedelta(minutes=s.lockout_minutes)
                user.failed_logins = 0
        audit(db, "auth.login", actor_id=user.id if user else None, actor_label=email, ip=ip, outcome="failure")
        db.commit()
        raise generic

    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    if user.password_hash is None or needs_rehash(user.password_hash) or not verify_password(data.password, user.password_hash):
        user.password_hash = hash_password(data.password)  # keep the hash in step with an edited plain password
    out = _issue(db, user, response, request)
    audit(db, "auth.login", actor_id=user.id, actor_label=email, ip=ip)
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    _require_csrf_header(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise Unauthorized("No active session.")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    now = utcnow()
    if not row:
        raise Unauthorized("No active session.")
    if row.revoked_at is not None:
        # Reuse of a rotated token: assume theft, revoke the whole family.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id,
                                              RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        audit(db, "auth.refresh_reuse", actor_id=row.user_id, ip=client_ip(request), outcome="failure")
        db.commit()
        response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
        raise Unauthorized("Session is no longer valid. Please sign in again.")
    if row.expires_at <= now:
        raise Unauthorized("Session expired. Please sign in again.")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise Unauthorized("Account is not active.")
    row.revoked_at = now
    out = _issue(db, user, response, request, family=row.family_id)
    db.commit()
    return out


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _require_csrf_header(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
        if row and row.revoked_at is None:
            db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id,
                                                  RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
            audit(db, "auth.logout", actor_id=row.user_id, ip=client_ip(request))
            db.commit()
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
def me(p: Principal = Depends(get_principal)):
    u = p.user
    return MeOut(id=u.id, full_name=u.full_name, email=u.email, employee_code=u.employee_code,
                 job_title=u.job_title, department=u.department.name if u.department else None,
                 location=u.location.name if u.location else None, timezone=u.timezone,
                 roles=sorted(p.roles), permissions=sorted(p.permissions),
                 support_group_ids=sorted(p.group_ids), lead_group_ids=sorted(p.lead_group_ids))


@router.post("/change-password", status_code=204)
def change_password(data: ChangePasswordIn, response: Response, p: Principal = Depends(get_principal),
                    db: Session = Depends(get_db)):
    user = db.get(User, p.id)
    if not check_user_password(user, data.current_password):
        raise BusinessRuleError("Current password is incorrect.", details=[{"field": "current_password"}])
    problems = validate_password_strength(data.new_password)
    if problems:
        raise BusinessRuleError("Password must contain " + ", ".join(problems) + ".",
                                details=[{"field": "new_password"}])
    set_user_password(user, data.new_password)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit_p(db, p, "auth.password_change", entity_type="user", entity_id=user.id)
    db.commit()
    response.status_code = 204
    return response
