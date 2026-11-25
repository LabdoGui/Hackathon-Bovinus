"""revisao humana

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25 23:46:45.949194

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f('ix_transactions_reviewed_by_id'), ['reviewed_by_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_transactions_reviewed_by_id_operators'), 'operators', ['reviewed_by_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_transactions_reviewed_by_id_operators'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_transactions_reviewed_by_id'))
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('reviewed_at')

