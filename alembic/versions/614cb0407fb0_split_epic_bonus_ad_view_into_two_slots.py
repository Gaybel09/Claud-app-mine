"""split epic_bonus_ad_view_id into two slots (2-video unlock flow)

Revision ID: 614cb0407fb0
Revises: 9b3462d9019e
Create Date: 2026-07-30T12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '614cb0407fb0'
down_revision: Union[str, None] = '9b3462d9019e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cubo Épico virou um fluxo de 2 vídeos (não 1) -- feature nova o
    # suficiente (commit anterior) que não há dado real de produção usando
    # a coluna antiga, então dropar em vez de migrar dado é seguro.
    op.drop_constraint('fk_mining_sessions_epic_bonus_ad_view_id_ad_views', 'mining_sessions', type_='foreignkey')
    op.drop_column('mining_sessions', 'epic_bonus_ad_view_id')

    op.add_column('mining_sessions', sa.Column('epic_bonus_ad_view_1_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_mining_sessions_epic_bonus_ad_view_1_id_ad_views',
        'mining_sessions', 'ad_views', ['epic_bonus_ad_view_1_id'], ['id'],
    )
    op.add_column('mining_sessions', sa.Column('epic_bonus_ad_view_2_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_mining_sessions_epic_bonus_ad_view_2_id_ad_views',
        'mining_sessions', 'ad_views', ['epic_bonus_ad_view_2_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_mining_sessions_epic_bonus_ad_view_2_id_ad_views', 'mining_sessions', type_='foreignkey')
    op.drop_column('mining_sessions', 'epic_bonus_ad_view_2_id')
    op.drop_constraint('fk_mining_sessions_epic_bonus_ad_view_1_id_ad_views', 'mining_sessions', type_='foreignkey')
    op.drop_column('mining_sessions', 'epic_bonus_ad_view_1_id')

    op.add_column('mining_sessions', sa.Column('epic_bonus_ad_view_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_mining_sessions_epic_bonus_ad_view_id_ad_views',
        'mining_sessions', 'ad_views', ['epic_bonus_ad_view_id'], ['id'],
    )
