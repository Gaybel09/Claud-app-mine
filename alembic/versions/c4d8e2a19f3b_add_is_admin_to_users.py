"""add is_admin to users

Revision ID: c4d8e2a19f3b
Revises: b3e7d1f9a2c8
Create Date: 2026-07-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d8e2a19f3b'
down_revision: Union[str, None] = 'b3e7d1f9a2c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('users', 'is_admin')
