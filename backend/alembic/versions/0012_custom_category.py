"""custom category text typed by the employee ("Other — type your own")

Revision ID: 0012_custom_category
Revises: 0011_drop_device_id
Create Date: 2026-11-19 16:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012_custom_category'
down_revision: Union[str, None] = '0011_drop_device_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('custom_category', sa.Unicode(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_column('custom_category')
