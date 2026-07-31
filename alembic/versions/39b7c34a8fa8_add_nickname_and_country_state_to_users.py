"""add nickname and country/state to users

Revision ID: 39b7c34a8fa8
Revises: 614cb0407fb0
Create Date: 2026-07-31 19:37:58.043251

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39b7c34a8fa8'
down_revision: Union[str, None] = '614cb0407fb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.add_column("users", sa.Column("state_code", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "state_code")
    op.drop_column("users", "country_code")
    op.drop_column("users", "nickname")
