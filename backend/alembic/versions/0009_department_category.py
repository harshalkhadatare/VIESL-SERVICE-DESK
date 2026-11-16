"""department category

Revision ID: 0009_department_category
Revises: 0008_ticket_series
Create Date: 2026-11-16 10:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009_department_category'
down_revision: Union[str, None] = '0008_ticket_series'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The company's department list (category + department) is filled in by the reference seed.
    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.Unicode(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.drop_column('category')
