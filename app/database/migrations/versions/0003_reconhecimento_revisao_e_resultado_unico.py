"""reconhecimento revisao e resultado unico

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25 23:38:04.498362

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('recognition_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default=sa.text("'[]'"), nullable=False))
        batch_op.add_column(sa.Column('net_weight_g', sa.Numeric(precision=12, scale=1), nullable=True))

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transactions_recognition_result_id'))
        batch_op.create_index(batch_op.f('ix_transactions_recognition_result_id'), ['recognition_result_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transactions_recognition_result_id'))
        batch_op.create_index(batch_op.f('ix_transactions_recognition_result_id'), ['recognition_result_id'], unique=False)

    with op.batch_alter_table('recognition_results', schema=None) as batch_op:
        batch_op.drop_column('net_weight_g')
        batch_op.drop_column('review_reasons')

