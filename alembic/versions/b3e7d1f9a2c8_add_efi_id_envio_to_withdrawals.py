"""add efi_id_envio to withdrawals

Revision ID: b3e7d1f9a2c8
Revises: 9a1c2f3b7d4e
Create Date: 2026-07-24 15:00:00.000000

"""
import hashlib
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e7d1f9a2c8'
down_revision: Union[str, None] = '9a1c2f3b7d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID_ENVIO_LENGTH = 32


def upgrade() -> None:
    op.add_column('withdrawals', sa.Column('efi_id_envio', sa.String(length=35), nullable=True))

    # Backfill: deriva efi_id_envio das linhas já existentes com a mesma
    # função usada em app.core.efi.derive_id_envio, para manter a
    # idempotência real de qualquer saque já enviado à Efí antes desta
    # migration.
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, idempotency_key FROM withdrawals")).fetchall()
    for row in rows:
        derived = hashlib.sha256(row.idempotency_key.encode("utf-8")).hexdigest()[:ID_ENVIO_LENGTH]
        connection.execute(
            sa.text("UPDATE withdrawals SET efi_id_envio = :efi_id_envio WHERE id = :id"),
            {"efi_id_envio": derived, "id": row.id},
        )

    op.alter_column('withdrawals', 'efi_id_envio', nullable=False)
    op.create_index(op.f('ix_withdrawals_efi_id_envio'), 'withdrawals', ['efi_id_envio'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_withdrawals_efi_id_envio'), table_name='withdrawals')
    op.drop_column('withdrawals', 'efi_id_envio')
