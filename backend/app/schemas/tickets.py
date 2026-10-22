from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORM, CodeRef, Ref, StrictIn, UserRef

ContactMethod = Literal["portal", "email", "phone", "teams"]
TicketType = Literal["incident", "service_request"]


class ErpDetailIn(StrictIn):
    erp_module: str | None = Field(None, max_length=60)
    transaction_type: str | None = Field(None, max_length=80)
    reference_no: str | None = Field(None, max_length=80)
    company_branch: str | None = Field(None, max_length=120)
    error_message: str | None = Field(None, max_length=4000)
    expected_result: str | None = Field(None, max_length=4000)
    actual_result: str | None = Field(None, max_length=4000)
    steps_to_reproduce: str | None = Field(None, max_length=4000)
    occurred_at: datetime | None = None
    business_impact: str | None = Field(None, max_length=500)
    workaround_available: bool | None = None

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("occurred_at must include a timezone offset")
        return v


class ErpDetailOut(ORM):
    erp_module: str | None = None
    transaction_type: str | None = None
    reference_no: str | None = None
    company_branch: str | None = None
    error_message: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    steps_to_reproduce: str | None = None
    occurred_at: datetime | None = None
    business_impact: str | None = None
    workaround_available: bool | None = None


class TicketCreate(StrictIn):
    subject: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=8000)
    category_id: int
    subcategory_id: int | None = None
    ticket_type: TicketType | None = None
    impact: int = Field(3, ge=1, le=3)
    urgency: int = Field(3, ge=1, le=3)
    contact_method: ContactMethod | None = "portal"
    related_ticket_number: str | None = Field(None, max_length=20)
    erp: ErpDetailIn | None = None


class DuplicateCheckIn(StrictIn):
    subject: str = Field(min_length=3, max_length=200)
    category_id: int | None = None


class StatusChangeIn(StrictIn):
    to_status: str = Field(max_length=30)
    reason: str | None = Field(None, max_length=1000)
    resolution_notes: str | None = Field(None, max_length=8000)
    root_cause: str | None = Field(None, max_length=4000)
    expected_version: int


class AssignIn(StrictIn):
    assignee_id: int | None = None          # IT administrator; None = unassign
    support_group_id: int | None = None     # optional: move to another support team
    reason: str | None = Field(None, max_length=500)
    expected_version: int


class VersionIn(StrictIn):
    expected_version: int


class PriorityChangeIn(StrictIn):
    impact: int = Field(ge=1, le=3)
    urgency: int = Field(ge=1, le=3)
    reason: str = Field(min_length=5, max_length=500)
    expected_version: int


class CommentIn(StrictIn):
    body: str = Field(min_length=1, max_length=8000)
    is_internal: bool = False


class RatingIn(StrictIn):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)


class LinkIn(StrictIn):
    target_number: str = Field(max_length=20)
    relation_type: Literal["duplicate_of", "related"] = "related"


class SlaOut(BaseModel):
    state: str
    percent_used: int
    remaining_business_minutes: int
    response_due_at: datetime
    resolution_due_at: datetime
    response_target_minutes: int
    resolution_target_minutes: int
    paused_minutes: int
    is_paused: bool
    response_breached: bool
    resolution_breached: bool
    escalation_level: int


class TicketListItem(BaseModel):
    number: str
    version: int
    assignee_id: int | None
    subject: str
    ticket_type: str
    status: CodeRef
    priority: CodeRef
    category: str
    requester: str
    department: str | None
    assignee: str | None
    support_group: str | None
    created_at: datetime
    updated_at: datetime
    sla_state: str | None
    resolution_due_at: datetime | None


class CommentOut(ORM):
    id: int
    body: str
    is_internal: bool
    created_at: datetime
    author: UserRef


class AttachmentOut(ORM):
    id: int
    original_name: str
    content_type: str
    size_bytes: int
    is_internal: bool
    created_at: datetime
    uploader: UserRef


class HistoryOut(ORM):
    id: int
    field: str
    old_value: str | None
    new_value: str | None
    reason: str | None
    is_internal: bool
    created_at: datetime
    actor: UserRef | None


class RelationOut(BaseModel):
    number: str
    subject: str
    status: str
    relation_type: str
    direction: Literal["outgoing", "incoming"]


class RatingOut(ORM):
    rating: int
    comment: str | None
    created_at: datetime


class TicketDetail(BaseModel):
    number: str
    version: int
    subject: str
    description: str
    ticket_type: str
    status: CodeRef
    priority: CodeRef
    impact: int
    urgency: int
    category: Ref
    subcategory: Ref | None
    requester: UserRef
    requester_phone: str | None
    department: Ref | None
    location: Ref | None
    support_group: Ref | None
    assignee: UserRef | None
    contact_method: str | None
    root_cause: str | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime
    first_response_at: datetime | None
    assigned_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    closure_reason: str | None
    reopen_count: int
    is_demo: bool
    erp: ErpDetailOut | None
    sla: SlaOut | None
    rating: RatingOut | None
    relations: list[RelationOut]
    # What the current user may do (UI hints; the server re-checks every action)
    can_work: bool
    can_assign: bool
    can_set_priority: bool
    can_comment_internal: bool
    can_rate: bool
    allowed_transitions: list[CodeRef]


class DuplicateCandidate(BaseModel):
    number: str
    subject: str
    status: str
    created_at: datetime
    score: float
