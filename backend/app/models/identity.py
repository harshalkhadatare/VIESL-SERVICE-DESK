from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Unicode, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, utcnow


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)


class Location(Base, TimestampMixin):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(255))
    permissions: Mapped[list["Permission"]] = relationship(secondary="role_permissions", lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(60), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(255))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), primary_key=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(Unicode(30), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Unicode(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(Unicode(30))
    job_title: Mapped[str | None] = mapped_column(Unicode(120))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    password_hash: Mapped[str | None] = mapped_column(Unicode(255))  # null when SSO-only
    auth_provider: Mapped[str] = mapped_column(Unicode(20), default="local", nullable=False)
    timezone: Mapped[str] = mapped_column(Unicode(60), default="Asia/Kolkata", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    department: Mapped[Department | None] = relationship(lazy="joined")
    location: Mapped[Location | None] = relationship(lazy="joined")
    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", lazy="selectin",
        primaryjoin="User.id==UserRole.user_id", secondaryjoin="Role.id==UserRole.role_id",
    )

    @property
    def role_codes(self) -> set[str]:
        return {r.code for r in self.roles}

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for r in self.roles for p in r.permissions}


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Unicode(64), unique=True, nullable=False)
    family_id: Mapped[str] = mapped_column(Unicode(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Unicode(255))


class SupportGroup(Base, TimestampMixin):
    __tablename__ = "support_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    email: Mapped[str | None] = mapped_column(Unicode(254))
    assignment_strategy: Mapped[str] = mapped_column(Unicode(20), default="manual", nullable=False)  # manual|round_robin|least_loaded
    last_assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)


class SupportGroupMember(Base):
    __tablename__ = "support_group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("support_groups.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    skills: Mapped[str | None] = mapped_column(Unicode(255))

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])
    group: Mapped[SupportGroup] = relationship(lazy="joined")


Index("ix_sgm_user", SupportGroupMember.user_id)
