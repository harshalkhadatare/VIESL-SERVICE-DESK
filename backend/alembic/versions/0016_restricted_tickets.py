"""tickets.is_restricted — tickets raised by the Managing Director are private to the MD and the assigned admin

Revision ID: 0016_restricted_tickets
Revises: 0015_task_attachments
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_restricted_tickets"
down_revision: Union[str, None] = "0015_task_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as b:
        b.add_column(sa.Column("is_restricted", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("tickets") as b:
        b.drop_column("is_restricted")
