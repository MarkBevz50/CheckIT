"""baseline: users, tenders, tender_items, price_history

The schema as `Base.metadata.create_all` plus the old startup `ALTER TABLE`s produced it
(price_source column, nullable unit_price), now with names from the naming convention.

Revision ID: 0001
Revises:
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('hashed_password', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_table('tenders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tender_type', sa.String(length=20), nullable=False),
    sa.Column('prozorro_id', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('expected_cost', sa.Float(), nullable=True),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('customer_name', sa.String(length=300), nullable=True),
    sa.Column('region', sa.String(length=100), nullable=True),
    sa.Column('total_amount', sa.Float(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('warranty_required', sa.Boolean(), nullable=True),
    sa.Column('requires_license', sa.Boolean(), nullable=True),
    sa.Column('project_documentation', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_tenders_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenders'))
    )
    op.create_index(op.f('ix_tenders_id'), 'tenders', ['id'], unique=False)
    op.create_index(op.f('ix_tenders_prozorro_id'), 'tenders', ['prozorro_id'], unique=True)
    op.create_index(op.f('ix_tenders_status'), 'tenders', ['status'], unique=False)
    op.create_index(op.f('ix_tenders_tender_type'), 'tenders', ['tender_type'], unique=False)
    op.create_index(op.f('ix_tenders_user_id'), 'tenders', ['user_id'], unique=False)
    op.create_table('tender_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tender_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('unit_name', sa.String(length=50), nullable=False),
    sa.Column('unit_price', sa.Float(), nullable=True),
    sa.Column('price_source', sa.String(length=20), server_default='tender', nullable=False),
    sa.Column('dk_code', sa.String(length=50), nullable=True),
    sa.Column('brand', sa.String(length=200), nullable=True),
    sa.Column('dstu_gost', sa.String(length=100), nullable=True),
    sa.Column('weight_per_unit_g', sa.Float(), nullable=True),
    sa.Column('shelf_life_days', sa.Integer(), nullable=True),
    sa.Column('specifications', sa.Text(), nullable=True),
    sa.Column('delivery_address', sa.String(length=500), nullable=True),
    sa.Column('delivery_deadline', sa.String(length=100), nullable=True),
    sa.Column('service_type', sa.String(length=100), nullable=True),
    sa.Column('period_start', sa.String(length=50), nullable=True),
    sa.Column('period_end', sa.String(length=50), nullable=True),
    sa.Column('qualification_requirements', sa.Text(), nullable=True),
    sa.Column('sla_description', sa.Text(), nullable=True),
    sa.Column('license_required', sa.Boolean(), nullable=True),
    sa.Column('location', sa.String(length=300), nullable=True),
    sa.Column('work_type', sa.String(length=100), nullable=True),
    sa.Column('object_address', sa.String(length=500), nullable=True),
    sa.Column('estimated_duration_days', sa.Integer(), nullable=True),
    sa.Column('technical_specs', sa.Text(), nullable=True),
    sa.Column('permit_required', sa.Boolean(), nullable=True),
    sa.Column('subcontracting_allowed', sa.Boolean(), nullable=True),
    sa.Column('materials_included', sa.Boolean(), nullable=True),
    sa.Column('warranty_months', sa.Integer(), nullable=True),
    sa.Column('extra_data', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['tender_id'], ['tenders.id'], name=op.f('fk_tender_items_tender_id_tenders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tender_items'))
    )
    op.create_index(op.f('ix_tender_items_id'), 'tender_items', ['id'], unique=False)
    op.create_index(op.f('ix_tender_items_tender_id'), 'tender_items', ['tender_id'], unique=False)
    op.create_table('price_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('source_store', sa.String(length=100), nullable=False),
    sa.Column('product_title', sa.String(length=500), nullable=True),
    sa.Column('product_url', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['tender_items.id'], name=op.f('fk_price_history_item_id_tender_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_history'))
    )
    op.create_index(op.f('ix_price_history_created_at'), 'price_history', ['created_at'], unique=False)
    op.create_index(op.f('ix_price_history_id'), 'price_history', ['id'], unique=False)
    op.create_index(op.f('ix_price_history_item_id'), 'price_history', ['item_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_price_history_item_id'), table_name='price_history')
    op.drop_index(op.f('ix_price_history_id'), table_name='price_history')
    op.drop_index(op.f('ix_price_history_created_at'), table_name='price_history')
    op.drop_table('price_history')
    op.drop_index(op.f('ix_tender_items_tender_id'), table_name='tender_items')
    op.drop_index(op.f('ix_tender_items_id'), table_name='tender_items')
    op.drop_table('tender_items')
    op.drop_index(op.f('ix_tenders_user_id'), table_name='tenders')
    op.drop_index(op.f('ix_tenders_tender_type'), table_name='tenders')
    op.drop_index(op.f('ix_tenders_status'), table_name='tenders')
    op.drop_index(op.f('ix_tenders_prozorro_id'), table_name='tenders')
    op.drop_index(op.f('ix_tenders_id'), table_name='tenders')
    op.drop_table('tenders')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
