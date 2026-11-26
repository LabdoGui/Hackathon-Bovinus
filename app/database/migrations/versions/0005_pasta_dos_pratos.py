"""pasta dos pratos

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26 02:54:44.677061

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('image_captures', schema=None) as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('export_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('image_captures', schema=None) as batch_op:
        batch_op.drop_column('export_path')
        batch_op.drop_column('label')

