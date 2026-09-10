"""symbol display name and logo

Revision ID: f1a4b8c2d3e5
Revises: c7d2e91a4f60
Create Date: 2026-09-10 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a4b8c2d3e5'
down_revision: Union[str, None] = 'c7d2e91a4f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('symbols', sa.Column('display_name', sa.String(length=64), nullable=True))
    op.add_column('symbols', sa.Column('logo_url', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('symbols', 'logo_url')
    op.drop_column('symbols', 'display_name')
