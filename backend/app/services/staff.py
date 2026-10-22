"""Who counts as IT staff (users whose roles grant ticket.work — i.e. IT Administrators)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Permission, RolePermission, SupportGroupMember, User, UserRole


def it_staff_query():
    return (select(User).join(UserRole, UserRole.user_id == User.id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(Permission.code == "ticket.work", User.is_active.is_(True))
            .distinct())


def it_staff(db: Session) -> list[User]:
    return sorted(db.scalars(it_staff_query()).unique().all(), key=lambda u: u.full_name)


def is_it_staff(db: Session, user_id: int) -> bool:
    return db.scalar(it_staff_query().where(User.id == user_id).with_only_columns(User.id).limit(1)) is not None


def group_staff_ids(db: Session, group_id: int | None) -> list[int]:
    """IT staff to alert for a support group: its active members, else every IT administrator."""
    ids: list[int] = []
    if group_id:
        staff = {u.id for u in it_staff(db)}
        ids = [uid for uid in db.scalars(select(SupportGroupMember.user_id).where(
            SupportGroupMember.group_id == group_id, SupportGroupMember.is_available.is_(True))) if uid in staff]
    return ids or [u.id for u in it_staff(db)]
