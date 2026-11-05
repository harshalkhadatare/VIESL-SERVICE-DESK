"""ticket number series

Revision ID: 0008_ticket_series
Revises: 0007_shared_email
Create Date: 2026-11-05 07:41:14.788943
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.models.base


revision: str = '0008_ticket_series'
down_revision: Union[str, None] = '0007_shared_email'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Numbers become IT-26-…, ERP-26-…, ITERP-26-… with a counter per series; existing rows keep counting the
    # older IT-2026-… numbers under the 'LEGACY' series (those numbers are never re-used).
    with op.batch_alter_table('ticket_sequences', schema=None) as batch_op:
        batch_op.add_column(sa.Column('series', sa.Unicode(length=10), server_default='LEGACY', nullable=False))
    with op.batch_alter_table('ticket_sequences', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('pk_ticket_sequences'), type_='primary')
        batch_op.create_primary_key(op.f('pk_ticket_sequences'), ['series', 'year'])


def downgrade() -> None:
    op.execute("DELETE FROM ticket_sequences WHERE series <> 'LEGACY'")
    with op.batch_alter_table('ticket_sequences', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('pk_ticket_sequences'), type_='primary')
        batch_op.create_primary_key(op.f('pk_ticket_sequences'), ['year'])
    with op.batch_alter_table('ticket_sequences', schema=None) as batch_op:
        batch_op.drop_column('series')
