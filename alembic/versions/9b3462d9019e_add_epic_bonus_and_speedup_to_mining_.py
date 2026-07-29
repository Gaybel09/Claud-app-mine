"""add epic bonus and speedup fields to mining_sessions

Revision ID: 9b3462d9019e
Revises: ef9028908c86
Create Date: 2026-07-29T22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b3462d9019e'
down_revision: Union[str, None] = 'ef9028908c86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'mining_sessions',
        sa.Column('epic_bonus_applied', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'mining_sessions',
        sa.Column('epic_bonus_ad_view_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_mining_sessions_epic_bonus_ad_view_id_ad_views',
        'mining_sessions', 'ad_views', ['epic_bonus_ad_view_id'], ['id'],
    )
    op.add_column(
        'mining_sessions',
        sa.Column('speedup_used', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'mining_sessions',
        sa.Column('speedup_ad_view_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_mining_sessions_speedup_ad_view_id_ad_views',
        'mining_sessions', 'ad_views', ['speedup_ad_view_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_mining_sessions_speedup_ad_view_id_ad_views', 'mining_sessions', type_='foreignkey')
    op.drop_column('mining_sessions', 'speedup_ad_view_id')
    op.drop_column('mining_sessions', 'speedup_used')
    op.drop_constraint('fk_mining_sessions_epic_bonus_ad_view_id_ad_views', 'mining_sessions', type_='foreignkey')
    op.drop_column('mining_sessions', 'epic_bonus_ad_view_id')
    op.drop_column('mining_sessions', 'epic_bonus_applied')
