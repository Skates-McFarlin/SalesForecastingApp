"""Initial migration (SQLite)

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'file',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('filedata', sa.LargeBinary(length=2097152), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'prediction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=True),
        sa.Column('product_name', sa.String(length=100), nullable=False, index=True),
        sa.Column('sku', sa.String(length=120), nullable=True, index=True),
        sa.Column('duration', sa.String(length=120), nullable=False),
        sa.Column('forecast', sa.String(length=120), nullable=False),
        sa.Column('actual_sales', sa.String(length=120), nullable=True),
        sa.Column('percent_change', sa.String(length=120), nullable=True),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('seasonality', sa.String(length=60), nullable=True),
        sa.Column('forecast_low', sa.String(length=120), nullable=True),
        sa.Column('forecast_high', sa.String(length=120), nullable=True),
        sa.Column('seasonality_note', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('summary_unverified', sa.Boolean(), nullable=True),
        sa.Column('history_months', sa.Integer(), nullable=True),
        sa.Column('has_data_gap', sa.Boolean(), nullable=True),
        sa.Column('forecast_method', sa.String(length=60), nullable=True),
        sa.Column('forecast_model', sa.String(length=60), nullable=True),
        sa.Column('extra_context', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['file.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Persistent catalog (Phase 0: the app becomes stateful) --------------------
    op.create_table(
        'product',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False, unique=True, index=True),
        sa.Column('sku', sa.String(length=120), nullable=True, index=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('attributes', sa.Text(), nullable=True),
        # Inventory state & economics (Phase 2)
        sa.Column('on_hand', sa.Float(), nullable=True),
        sa.Column('on_order', sa.Float(), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('unit_cost', sa.Float(), nullable=True),
        sa.Column('moq', sa.Integer(), nullable=True),
        sa.Column('case_pack', sa.Integer(), nullable=True),
        sa.Column('inventory_updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'sales_record',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False, index=True),
        sa.Column('date', sa.Date(), nullable=False, index=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['product.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'date', name='uq_sales_product_date'),
    )
    # Decision & outcome ledger (Phase 1: the app grades its own forecasts) -----
    op.create_table(
        'forecast_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True, index=True),
        sa.Column('grain', sa.String(length=20), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('horizon', sa.Integer(), nullable=False),
        sa.Column('service_level', sa.Float(), nullable=False),
        sa.Column('catalog_products', sa.Integer(), nullable=True),
        sa.Column('catalog_date_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'ledger_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False, index=True),
        sa.Column('product_key', sa.String(length=200), nullable=False, index=True),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('sku', sa.String(length=120), nullable=True),
        sa.Column('forecast', sa.Float(), nullable=False),
        sa.Column('raw_forecast', sa.Float(), nullable=True),
        sa.Column('forecast_low', sa.Float(), nullable=True),
        sa.Column('forecast_high', sa.Float(), nullable=True),
        sa.Column('recommended_order', sa.Float(), nullable=True),
        sa.Column('safety_stock', sa.Float(), nullable=True),
        sa.Column('actual', sa.Float(), nullable=True),
        sa.Column('reconciled', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['forecast_run.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Replenishment orders (Phase 2.5): self-maintaining on-order + learned lead
    op.create_table(
        'purchase_order',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False, index=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('placed_on', sa.Date(), nullable=False),
        sa.Column('expected_on', sa.Date(), nullable=True),
        sa.Column('received_on', sa.Date(), nullable=True),
        sa.Column('received_qty', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['product.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Business-level inventory defaults (Phase 2) - a single row (id=1)
    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('default_lead_time_days', sa.Integer(), nullable=False),
        sa.Column('review_period_days', sa.Integer(), nullable=False),
        sa.Column('service_level', sa.Float(), nullable=False),
        sa.Column('holding_cost_rate', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('settings')
    op.drop_table('purchase_order')
    op.drop_table('ledger_item')
    op.drop_table('forecast_run')
    op.drop_table('sales_record')
    op.drop_table('product')
    op.drop_table('prediction')
    op.drop_table('file')
