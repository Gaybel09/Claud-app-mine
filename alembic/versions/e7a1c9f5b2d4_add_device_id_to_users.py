"""add device_id to users

Revision ID: e7a1c9f5b2d4
Revises: c4d8e2a19f3b
Create Date: 2026-07-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a1c9f5b2d4'
down_revision: Union[str, None] = 'c4d8e2a19f3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('device_id', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_users_device_id'), 'users', ['device_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_device_id'), table_name='users')
    op.drop_column('users', 'device_id')
