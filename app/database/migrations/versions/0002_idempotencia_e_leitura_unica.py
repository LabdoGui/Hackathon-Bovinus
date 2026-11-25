"""idempotencia e leitura unica

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25 23:18:30.438452

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('idempotency_fingerprint', sa.String(length=64), nullable=True))
        batch_op.drop_index(batch_op.f('ix_transactions_scale_reading_id'))
        batch_op.create_index(batch_op.f('ix_transactions_scale_reading_id'), ['scale_reading_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transactions_scale_reading_id'))
        batch_op.create_index(batch_op.f('ix_transactions_scale_reading_id'), ['scale_reading_id'], unique=False)
        batch_op.drop_column('idempotency_fingerprint')

