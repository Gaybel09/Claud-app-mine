"""add reward_config table

Revision ID: e0e8133a7c97
Revises: e7a1c9f5b2d4
Create Date: 2026-07-25T16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0e8133a7c97'
down_revision: Union[str, None] = 'e7a1c9f5b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reward_config',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('value_per_session', sa.Numeric(precision=10, scale=2), server_default='0.30', nullable=False),
    sa.Column('avg_ecpm', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_reward_config_singleton'),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute(
        "INSERT INTO reward_config (id, value_per_session, avg_ecpm, updated_at) "
        "VALUES (1, 0.30, NULL, now())"
    )


def downgrade() -> None:
    op.drop_table('reward_config')
