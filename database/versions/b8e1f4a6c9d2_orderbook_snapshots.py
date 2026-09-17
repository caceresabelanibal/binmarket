"""orderbook snapshots

Revision ID: b8e1f4a6c9d2
Revises: f1a4b8c2d3e5
Create Date: 2026-09-17 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e1f4a6c9d2'
down_revision: Union[str, None] = 'f1a4b8c2d3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'orderbook_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('best_bid', sa.Float(), nullable=False),
        sa.Column('best_ask', sa.Float(), nullable=False),
        sa.Column('mid_price', sa.Float(), nullable=False),
        sa.Column('bid_volume_top5', sa.Float(), nullable=False),
        sa.Column('ask_volume_top5', sa.Float(), nullable=False),
        sa.Column('imbalance_pct', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_orderbook_snapshots_symbol'), 'orderbook_snapshots', ['symbol'], unique=False)
    op.create_index(op.f('ix_orderbook_snapshots_captured_at'), 'orderbook_snapshots', ['captured_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_orderbook_snapshots_captured_at'), table_name='orderbook_snapshots')
    op.drop_index(op.f('ix_orderbook_snapshots_symbol'), table_name='orderbook_snapshots')
    op.drop_table('orderbook_snapshots')
