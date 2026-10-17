"""Notifications, knowledge base (read + search), users/roles admin and audit log."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require
from app.core.database import get_db
from app.core.errors import BusinessRuleError, NotFound
from app.models import (
    AuditLog, Category, KnowledgeArticle, Notification, RefreshToken, Role, User, UserRole, utcnow,
)
from app.schemas.common import Page, StrictIn
from app.services.audit import audit_p

router = APIRouter()


# ------------------------------------------------------------------ notifications
class NotificationOut(BaseModel):
    id: int
    event: str
    title: str
    body: str | None
    link: str | None
    is_read: bool
    created_at: datetime


@router.get("/notifications", response_model=Page[NotificationOut], tags=["Notifications"])
def notifications(unread_only: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == p.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[NotificationOut.model_validate(n, from_attributes=True) for n in rows],
                total=total, page=page, page_size=page_size)


@router.get("/notifications/unread-count", tags=["Notifications"])
def unread_count(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return {"count": db.scalar(select(func.count()).select_from(Notification)
                               .where(Notification.user_id == p.id, Notification.is_read.is_(False)))}


@router.post("/notifications/{nid}/read", status_code=204, tags=["Notifications"])
def mark_read(nid: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    n = db.scalar(select(Notification).where(Notification.id == nid, Notification.user_id == p.id))
    if not n:
        raise NotFound("Notification not found.")
    n.is_read = True
    db.commit()
    return Response(status_code=204)


@router.post("/notifications/read-all", status_code=204, tags=["Notifications"])
def mark_all(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == p.id, Notification.is_read.is_(False))
               .values(is_read=True))
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ knowledge base
class ArticleListOut(BaseModel):
    id: int
    title: str
    category: str | None
    keywords: str | None
    updated_at: datetime
    view_count: int


class ArticleOut(ArticleListOut):
    problem: str
    solution: str
    author: str
    version: int
    published_at: datetime | None


def _kb_visible(p: Principal):
    if p.can("kb.manage"):
        return KnowledgeArticle.status != "retired"
    return KnowledgeArticle.status == "published"


@router.get("/kb/articles", response_model=list[ArticleListOut], tags=["Knowledge base"])
def kb_search(q: str | None = Query(None, max_length=100), category_id: int | None = None,
              limit: int = Query(20, ge=1, le=50), p: Principal = Depends(require("kb.view")),
              db: Session = Depends(get_db)):
    stmt = select(KnowledgeArticle, Category.name).outerjoin(Category, Category.id == KnowledgeArticle.category_id) \
        .where(_kb_visible(p))
    if category_id:
        stmt = stmt.where(KnowledgeArticle.category_id == category_id)
    rows = db.execute(stmt.order_by(KnowledgeArticle.view_count.desc())).all()
    if q:
        words = [w for w in q.lower().split() if len(w) > 2][:8]

        def score(a: KnowledgeArticle) -> int:
            hay_t, hay_k = a.title.lower(), (a.keywords or "").lower()
            return sum(3 * (w in hay_t) + 2 * (w in hay_k) + (w in a.problem.lower()) for w in words)
        scored = [(score(a), a, c) for a, c in rows]
        rows = [(a, c) for s, a, c in sorted(scored, key=lambda x: -x[0]) if s > 0]
    return [ArticleListOut(id=a.id, title=a.title, category=c, keywords=a.keywords, updated_at=a.updated_at,
                           view_count=a.view_count) for a, c in rows[:limit]]


@router.get("/kb/articles/{aid}", response_model=ArticleOut, tags=["Knowledge base"])
def kb_article(aid: int, p: Principal = Depends(require("kb.view")), db: Session = Depends(get_db)):
    a = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == aid, _kb_visible(p)))
    if not a:
        raise NotFound("Article not found.")
    a.view_count += 1
    db.commit()
    cat = db.get(Category, a.category_id) if a.category_id else None
    return ArticleOut(id=a.id, title=a.title, category=cat.name if cat else None, keywords=a.keywords,
                      updated_at=a.updated_at, view_count=a.view_count, problem=a.problem, solution=a.solution,
                      author=a.author.full_name, version=a.version, published_at=a.published_at)


# ------------------------------------------------------------------ admin: users & roles
class UserAdminOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    email: str
    department: str | None
    location: str | None
    is_active: bool
    is_demo: bool
    roles: list[str]
    last_login_at: datetime | None
    locked: bool


class RolesIn(StrictIn):
    roles: list[str] = Field(min_length=1, max_length=5)


class ActiveIn(StrictIn):
    is_active: bool


def _user_out(u: User) -> UserAdminOut:
    return UserAdminOut(id=u.id, employee_code=u.employee_code, full_name=u.full_name, email=u.email,
                        department=u.department.name if u.department else None,
                        location=u.location.name if u.location else None, is_active=u.is_active,
                        is_demo=u.is_demo, roles=sorted(u.role_codes), last_login_at=u.last_login_at,
                        locked=bool(u.locked_until and u.locked_until > utcnow()))


@router.get("/admin/roles", tags=["Administration"])
def list_roles(p: Principal = Depends(require("user.manage")), db: Session = Depends(get_db)):
    return [{"code": r.code, "name": r.name, "description": r.description,
             "permissions": sorted(x.code for x in r.permissions)}
            for r in db.scalars(select(Role).order_by(Role.id))]


@router.get("/admin/users", response_model=Page[UserAdminOut], tags=["Administration"])
def list_users(q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1),
               page_size: int = Query(25, ge=1, le=100), p: Principal = Depends(require("user.manage")),
               db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.employee_code.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.full_name).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[_user_out(u) for u in rows], total=total, page=page, page_size=page_size)


@router.put("/admin/users/{uid}/roles", response_model=UserAdminOut, tags=["Administration"])
def set_roles(uid: int, data: RolesIn, p: Principal = Depends(require("user.manage")),
              db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise NotFound("User not found.")
    roles = db.scalars(select(Role).where(Role.code.in_(set(data.roles)))).all()
    if len(roles) != len(set(data.roles)):
        raise BusinessRuleError("Unknown role code.")
    if u.id == p.id and "it_admin" not in {r.code for r in roles}:
        raise BusinessRuleError("You cannot remove your own administrator role.")
    before = sorted(u.role_codes)
    db.execute(UserRole.__table__.delete().where(UserRole.user_id == u.id))
    for r in roles:
        db.add(UserRole(user_id=u.id, role_id=r.id, granted_by=p.id))
    # Force re-login so new permissions apply everywhere promptly
    db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit_p(db, p, "admin.roles_change", entity_type="user", entity_id=u.id,
            detail={"before": before, "after": sorted(r.code for r in roles)})
    db.commit()
    db.refresh(u)
    db.expire(u, ["roles"])
    return _user_out(u)


@router.patch("/admin/users/{uid}/active", response_model=UserAdminOut, tags=["Administration"])
def set_active(uid: int, data: ActiveIn, p: Principal = Depends(require("user.manage")),
               db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise NotFound("User not found.")
    if u.id == p.id and not data.is_active:
        raise BusinessRuleError("You cannot deactivate your own account.")
    u.is_active = data.is_active
    if not data.is_active:
        db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=utcnow()))
    else:
        u.locked_until, u.failed_logins = None, 0
    audit_p(db, p, "admin.user_active", entity_type="user", entity_id=u.id, detail={"is_active": data.is_active})
    db.commit()
    return _user_out(u)


# ------------------------------------------------------------------ audit log
class AuditOut(BaseModel):
    id: int
    created_at: datetime
    actor_label: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    detail: str | None
    ip_address: str | None
    outcome: str


@router.get("/audit-logs", response_model=Page[AuditOut], tags=["Audit"])
def audit_logs(action: str | None = Query(None, max_length=60), actor: str | None = Query(None, max_length=100),
               entity_id: str | None = Query(None, max_length=40), page: int = Query(1, ge=1),
               page_size: int = Query(50, ge=1, le=200), p: Principal = Depends(require("audit.view")),
               db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    if actor:
        stmt = stmt.where(AuditLog.actor_label.ilike(f"%{actor}%"))
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[AuditOut.model_validate(r, from_attributes=True) for r in rows], total=total, page=page,
                page_size=page_size)
