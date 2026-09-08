"""real account snapshots

Revision ID: c7d2e91a4f60
Revises: a3f8c21b9d4e
Create Date: 2026-08-29 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d2e91a4f60'
down_revision: Union[str, None] = 'a3f8c21b9d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'real_account_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('taken_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('total_usdt', sa.Float(), nullable=False),
        sa.Column('total_ars', sa.Float(), nullable=True),
        sa.Column('usdt_ars_rate', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_real_account_snapshots_taken_at'), 'real_account_snapshots', ['taken_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_real_account_snapshots_taken_at'), table_name='real_account_snapshots')
    op.drop_table('real_account_snapshots')
