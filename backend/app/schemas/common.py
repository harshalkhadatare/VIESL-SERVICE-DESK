from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StrictIn(BaseModel):
    """Input models reject unknown fields so protected attributes cannot be smuggled in."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Ref(ORM):
    id: int
    name: str


class CodeRef(ORM):
    code: str
    name: str


class UserRef(ORM):
    id: int
    full_name: str
    email: str | None = None


class Message(BaseModel):
    message: str


class TimestampOut(ORM):
    created_at: datetime
    updated_at: datetime
