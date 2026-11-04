"""per-user ticket flags: starred + last viewed

Revision ID: 0004_ticket_user_flags
Revises: 0003_password_plain
Create Date: 2026-11-04 13:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.models.base


revision: str = '0004_ticket_user_flags'
down_revision: Union[str, None] = '0003_password_plain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ticket_user_flags',
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('starred', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('starred_at', app.models.base.UTCDateTime(), nullable=True),
        sa.Column('viewed_at', app.models.base.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name=op.f('fk_ticket_user_flags_ticket_id_tickets')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ticket_user_flags_user_id_users')),
        sa.PrimaryKeyConstraint('ticket_id', 'user_id', name=op.f('pk_ticket_user_flags')),
    )
    op.create_index('ix_ticket_user_flags_user_starred', 'ticket_user_flags', ['user_id', 'starred'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ticket_user_flags_user_starred', table_name='ticket_user_flags')
    op.drop_table('ticket_user_flags')
