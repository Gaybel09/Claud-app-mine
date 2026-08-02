"""add weekly mission multiplier to users

Revision ID: e4fd8d617c60
Revises: 39b7c34a8fa8
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4fd8d617c60'
down_revision: Union[str, None] = '39b7c34a8fa8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("weekly_mission_multiplier_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "weekly_mission_multiplier_until")
