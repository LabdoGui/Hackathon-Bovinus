"""esquema inicial

Revision ID: 0001
Revises:
Create Date: 2026-11-25 22:57:05.709160

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ingredients',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('unit', sa.Enum('kg', 'l', 'un', name='ingredientunit', native_enum=False, length=8), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('unit_cost >= 0', name=op.f('ck_ingredients_unit_cost_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingredients')),
    sa.UniqueConstraint('name', name=op.f('uq_ingredients_name'))
    )
    with op.batch_alter_table('ingredients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ingredients_active'), ['active'], unique=False)
        batch_op.create_index(batch_op.f('ix_ingredients_created_at'), ['created_at'], unique=False)

    op.create_table('operators',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('username', sa.String(length=60), nullable=False),
    sa.Column('role', sa.Enum('operator', 'manager', 'admin', name='operatorrole', native_enum=False, length=16), nullable=False),
    sa.Column('api_key_hash', sa.String(length=64), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_operators')),
    sa.UniqueConstraint('api_key_hash', name=op.f('uq_operators_api_key_hash')),
    sa.UniqueConstraint('username', name=op.f('uq_operators_username'))
    )
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_operators_created_at'), ['created_at'], unique=False)

    op.create_table('recipes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('yield_weight_g', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('yield_portions', sa.Integer(), nullable=True),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('yield_portions IS NULL OR yield_portions > 0', name=op.f('ck_recipes_yield_portions_positive')),
    sa.CheckConstraint('yield_weight_g > 0', name=op.f('ck_recipes_yield_weight_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recipes')),
    sa.UniqueConstraint('name', name=op.f('uq_recipes_name'))
    )
    with op.batch_alter_table('recipes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipes_active'), ['active'], unique=False)
        batch_op.create_index(batch_op.f('ix_recipes_created_at'), ['created_at'], unique=False)

    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('action', sa.Enum('create', 'update', 'delete', 'correction', 'status_change', 'hardware_failure', name='auditaction', native_enum=False, length=24), nullable=False),
    sa.Column('operator_id', sa.Uuid(), nullable=True),
    sa.Column('before', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('after', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], name=op.f('fk_audit_logs_operator_id_operators'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index('ix_audit_logs_entity', ['entity_type', 'entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_operator_id'), ['operator_id'], unique=False)

    op.create_table('foods',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('recognition_class', sa.String(length=80), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('recipe_id', sa.Uuid(), nullable=True),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], name=op.f('fk_foods_recipe_id_recipes'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_foods')),
    sa.UniqueConstraint('name', name=op.f('uq_foods_name')),
    sa.UniqueConstraint('recognition_class', name=op.f('uq_foods_recognition_class'))
    )
    with op.batch_alter_table('foods', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_foods_active'), ['active'], unique=False)
        batch_op.create_index(batch_op.f('ix_foods_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_foods_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_foods_recipe_id'), ['recipe_id'], unique=False)

    op.create_table('image_captures',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Enum('webcam', 'upload', 'mock', name='capturesource', native_enum=False, length=16), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('mime_type', sa.String(length=32), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('brightness', sa.Float(), nullable=True),
    sa.Column('sharpness', sa.Float(), nullable=True),
    sa.Column('is_dark', sa.Boolean(), nullable=False),
    sa.Column('is_blurry', sa.Boolean(), nullable=False),
    sa.Column('device_index', sa.Integer(), nullable=True),
    sa.Column('operator_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_image_captures_size_positive')),
    sa.CheckConstraint('width > 0 AND height > 0', name=op.f('ck_image_captures_dimensions_positive')),
    sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], name=op.f('fk_image_captures_operator_id_operators'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_image_captures')),
    sa.UniqueConstraint('file_path', name=op.f('uq_image_captures_file_path'))
    )
    with op.batch_alter_table('image_captures', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_image_captures_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_image_captures_operator_id'), ['operator_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_image_captures_sha256'), ['sha256'], unique=False)

    op.create_table('recipe_ingredients',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('recipe_id', sa.Uuid(), nullable=False),
    sa.Column('ingredient_id', sa.Uuid(), nullable=False),
    sa.Column('gross_quantity', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('net_quantity', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('gross_quantity > 0', name=op.f('ck_recipe_ingredients_gross_quantity_positive')),
    sa.CheckConstraint('net_quantity IS NULL OR (net_quantity > 0 AND net_quantity <= gross_quantity)', name=op.f('ck_recipe_ingredients_net_quantity_valid')),
    sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], name=op.f('fk_recipe_ingredients_ingredient_id_ingredients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], name=op.f('fk_recipe_ingredients_recipe_id_recipes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recipe_ingredients')),
    sa.UniqueConstraint('recipe_id', 'ingredient_id', name=op.f('uq_recipe_ingredients_recipe_id_ingredient_id'))
    )
    with op.batch_alter_table('recipe_ingredients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipe_ingredients_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_recipe_ingredients_ingredient_id'), ['ingredient_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_recipe_ingredients_recipe_id'), ['recipe_id'], unique=False)

    op.create_table('scale_readings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('mode', sa.Enum('mock', 'serial', 'manual', name='scalemode', native_enum=False, length=16), nullable=False),
    sa.Column('gross_weight_g', sa.Numeric(precision=12, scale=1), nullable=True),
    sa.Column('tare_g', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('net_weight_g', sa.Numeric(precision=12, scale=1), nullable=True),
    sa.Column('stable', sa.Boolean(), nullable=False),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('raw_data', sa.String(length=255), nullable=True),
    sa.Column('error', sa.String(length=255), nullable=True),
    sa.Column('operator_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('gross_weight_g IS NULL OR gross_weight_g >= 0', name=op.f('ck_scale_readings_gross_weight_non_negative')),
    sa.CheckConstraint('tare_g >= 0', name=op.f('ck_scale_readings_tare_non_negative')),
    sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], name=op.f('fk_scale_readings_operator_id_operators'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scale_readings'))
    )
    with op.batch_alter_table('scale_readings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scale_readings_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_scale_readings_operator_id'), ['operator_id'], unique=False)

    op.create_table('recognition_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('image_capture_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.Enum('mock', 'api', 'local', name='recognitionmode', native_enum=False, length=16), nullable=False),
    sa.Column('model_name', sa.String(length=120), nullable=True),
    sa.Column('model_version', sa.String(length=60), nullable=True),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('status', sa.Enum('success', 'uncertain', 'failed', name='recognitionstatus', native_enum=False, length=16), nullable=False),
    sa.Column('overall_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
    sa.Column('requires_review', sa.Boolean(), nullable=False),
    sa.Column('detections', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('error', sa.String(length=255), nullable=True),
    sa.Column('processing_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('overall_confidence IS NULL OR (overall_confidence >= 0 AND overall_confidence <= 1)', name=op.f('ck_recognition_results_confidence_range')),
    sa.ForeignKeyConstraint(['image_capture_id'], ['image_captures.id'], name=op.f('fk_recognition_results_image_capture_id_image_captures'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recognition_results'))
    )
    with op.batch_alter_table('recognition_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recognition_results_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_recognition_results_image_capture_id'), ['image_capture_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_recognition_results_status'), ['status'], unique=False)

    op.create_table('transactions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=True),
    sa.Column('status', sa.Enum('draft', 'pending_review', 'confirmed', 'cancelled', name='transactionstatus', native_enum=False, length=20), nullable=False),
    sa.Column('operator_id', sa.Uuid(), nullable=True),
    sa.Column('scale_reading_id', sa.Uuid(), nullable=True),
    sa.Column('image_capture_id', sa.Uuid(), nullable=True),
    sa.Column('recognition_result_id', sa.Uuid(), nullable=True),
    sa.Column('gross_weight_g', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('tare_g', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('net_weight_g', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('price_per_kg', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('charged_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('food_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('gross_margin', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('gross_margin_pct', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('requires_review', sa.Boolean(), nullable=False),
    sa.Column('review_reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('charged_amount >= 0', name=op.f('ck_transactions_charged_non_negative')),
    sa.CheckConstraint('food_cost IS NULL OR food_cost >= 0', name=op.f('ck_transactions_food_cost_non_negative')),
    sa.CheckConstraint('gross_weight_g >= 0', name=op.f('ck_transactions_gross_weight_non_negative')),
    sa.CheckConstraint('net_weight_g >= 0', name=op.f('ck_transactions_net_weight_non_negative')),
    sa.CheckConstraint('price_per_kg >= 0', name=op.f('ck_transactions_price_non_negative')),
    sa.CheckConstraint('tare_g >= 0', name=op.f('ck_transactions_tare_non_negative')),
    sa.ForeignKeyConstraint(['image_capture_id'], ['image_captures.id'], name=op.f('fk_transactions_image_capture_id_image_captures'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], name=op.f('fk_transactions_operator_id_operators'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['recognition_result_id'], ['recognition_results.id'], name=op.f('fk_transactions_recognition_result_id_recognition_results'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['scale_reading_id'], ['scale_readings.id'], name=op.f('fk_transactions_scale_reading_id_scale_readings'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transactions')),
    sa.UniqueConstraint('code', name=op.f('uq_transactions_code')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_transactions_idempotency_key'))
    )
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_transactions_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_image_capture_id'), ['image_capture_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_operator_id'), ['operator_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_recognition_result_id'), ['recognition_result_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_requires_review'), ['requires_review'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_scale_reading_id'), ['scale_reading_id'], unique=False)
        batch_op.create_index('ix_transactions_status_created_at', ['status', 'created_at'], unique=False)

    op.create_table('transaction_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('transaction_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('food_id', sa.Uuid(), nullable=True),
    sa.Column('food_name', sa.String(length=120), nullable=False),
    sa.Column('recognition_class', sa.String(length=80), nullable=True),
    sa.Column('source', sa.Enum('recognition', 'manual', name='itemsource', native_enum=False, length=16), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=5, scale=4), nullable=True),
    sa.Column('proportion', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('weight_g', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('cost_per_kg', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('is_corrected', sa.Boolean(), nullable=False),
    sa.Column('original_food_id', sa.Uuid(), nullable=True),
    sa.Column('original_food_name', sa.String(length=120), nullable=True),
    sa.Column('original_proportion', sa.Numeric(precision=5, scale=4), nullable=True),
    sa.Column('original_weight_g', sa.Numeric(precision=12, scale=1), nullable=True),
    sa.Column('extra', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 1)', name=op.f('ck_transaction_items_confidence_range')),
    sa.CheckConstraint('cost IS NULL OR cost >= 0', name=op.f('ck_transaction_items_cost_non_negative')),
    sa.CheckConstraint('proportion >= 0 AND proportion <= 1', name=op.f('ck_transaction_items_proportion_range')),
    sa.CheckConstraint('weight_g >= 0', name=op.f('ck_transaction_items_weight_non_negative')),
    sa.ForeignKeyConstraint(['food_id'], ['foods.id'], name=op.f('fk_transaction_items_food_id_foods'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['original_food_id'], ['foods.id'], name=op.f('fk_transaction_items_original_food_id_foods'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_transaction_items_transaction_id_transactions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transaction_items'))
    )
    with op.batch_alter_table('transaction_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_transaction_items_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_transaction_items_food_id'), ['food_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transaction_items_transaction_id'), ['transaction_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('transaction_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transaction_items_transaction_id'))
        batch_op.drop_index(batch_op.f('ix_transaction_items_food_id'))
        batch_op.drop_index(batch_op.f('ix_transaction_items_created_at'))

    op.drop_table('transaction_items')
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index('ix_transactions_status_created_at')
        batch_op.drop_index(batch_op.f('ix_transactions_scale_reading_id'))
        batch_op.drop_index(batch_op.f('ix_transactions_requires_review'))
        batch_op.drop_index(batch_op.f('ix_transactions_recognition_result_id'))
        batch_op.drop_index(batch_op.f('ix_transactions_operator_id'))
        batch_op.drop_index(batch_op.f('ix_transactions_image_capture_id'))
        batch_op.drop_index(batch_op.f('ix_transactions_created_at'))

    op.drop_table('transactions')
    with op.batch_alter_table('recognition_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recognition_results_status'))
        batch_op.drop_index(batch_op.f('ix_recognition_results_image_capture_id'))
        batch_op.drop_index(batch_op.f('ix_recognition_results_created_at'))

    op.drop_table('recognition_results')
    with op.batch_alter_table('scale_readings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scale_readings_operator_id'))
        batch_op.drop_index(batch_op.f('ix_scale_readings_created_at'))

    op.drop_table('scale_readings')
    with op.batch_alter_table('recipe_ingredients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipe_ingredients_recipe_id'))
        batch_op.drop_index(batch_op.f('ix_recipe_ingredients_ingredient_id'))
        batch_op.drop_index(batch_op.f('ix_recipe_ingredients_created_at'))

    op.drop_table('recipe_ingredients')
    with op.batch_alter_table('image_captures', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_image_captures_sha256'))
        batch_op.drop_index(batch_op.f('ix_image_captures_operator_id'))
        batch_op.drop_index(batch_op.f('ix_image_captures_created_at'))

    op.drop_table('image_captures')
    with op.batch_alter_table('foods', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_foods_recipe_id'))
        batch_op.drop_index(batch_op.f('ix_foods_created_at'))
        batch_op.drop_index(batch_op.f('ix_foods_category'))
        batch_op.drop_index(batch_op.f('ix_foods_active'))

    op.drop_table('foods')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_logs_operator_id'))
        batch_op.drop_index('ix_audit_logs_entity')
        batch_op.drop_index(batch_op.f('ix_audit_logs_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_action'))

    op.drop_table('audit_logs')
    with op.batch_alter_table('recipes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipes_created_at'))
        batch_op.drop_index(batch_op.f('ix_recipes_active'))

    op.drop_table('recipes')
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_operators_created_at'))

    op.drop_table('operators')
    with op.batch_alter_table('ingredients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ingredients_created_at'))
        batch_op.drop_index(batch_op.f('ix_ingredients_active'))

    op.drop_table('ingredients')
