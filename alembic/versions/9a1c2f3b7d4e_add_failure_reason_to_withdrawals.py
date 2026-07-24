"""add failure_reason to withdrawals

Revision ID: 9a1c2f3b7d4e
Revises: ffad2a6737cf
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a1c2f3b7d4e'
down_revision: Union[str, None] = 'ffad2a6737cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('withdrawals', sa.Column('failure_reason', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('withdrawals', 'failure_reason')
