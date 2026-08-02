"""add weekly_missions_completed to users

Revision ID: 280297668ef9
Revises: e4fd8d617c60
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '280297668ef9'
down_revision: Union[str, None] = 'e4fd8d617c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("weekly_missions_completed", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "weekly_missions_completed")
