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
        sa.Column('file_id', sa.Integer(), nullable=False),
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


def downgrade():
    op.drop_table('prediction')
    op.drop_table('file')
