"""losing streak reset at

Revision ID: a3f8c21b9d4e
Revises: 6027786c89b3
Create Date: 2026-08-28 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c21b9d4e'
down_revision: Union[str, None] = '6027786c89b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL is a meaningful default (never cleared) - no server_default needed.
    op.add_column('settings', sa.Column('losing_streak_reset_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('settings', 'losing_streak_reset_at')
