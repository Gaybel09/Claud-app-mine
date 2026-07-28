"""add fund_adjustments table and reward_fund.total_adjustments

Revision ID: ef9028908c86
Revises: e0e8133a7c97
Create Date: 2026-07-27T12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef9028908c86'
down_revision: Union[str, None] = 'e0e8133a7c97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reward_fund',
        sa.Column('total_adjustments', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    )
    op.create_table('fund_adjustments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('balance_after', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('admin_user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('amount != 0', name='ck_fund_adjustments_amount_nonzero'),
    sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fund_adjustments_admin_user_id'), 'fund_adjustments', ['admin_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fund_adjustments_admin_user_id'), table_name='fund_adjustments')
    op.drop_table('fund_adjustments')
    op.drop_column('reward_fund', 'total_adjustments')
