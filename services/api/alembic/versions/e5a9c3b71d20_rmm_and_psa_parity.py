"""RMM and PSA parity: patch policies and approvals, reboot state, alert
thresholds, customers, contacts, contracts and invoices.

Revision ID: e5a9c3b71d20
Revises: d8f6a204b913
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a9c3b71d20'
down_revision: Union[str, None] = 'd8f6a204b913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    # Non-production databases may already hold new tables via create_all().
    if 'customers' not in existing:
        op.create_table('customers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('domain', sa.String(255), nullable=False),
            sa.Column('phone', sa.String(50), nullable=False),
            sa.Column('notes', sa.Text(), nullable=False),
            _timestamps(),
            sa.UniqueConstraint('org_id', 'name', name='uq_customer_org_name'))
        op.create_index('ix_customers_org_id', 'customers', ['org_id'])
    if 'contacts' not in existing:
        op.create_table('contacts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('phone', sa.String(50), nullable=False),
            sa.Column('role', sa.String(100), nullable=False))
        op.create_index('ix_contacts_org_id', 'contacts', ['org_id'])
        op.create_index('ix_contacts_customer_id', 'contacts', ['customer_id'])
    if 'contracts' not in existing:
        op.create_table('contracts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
            sa.Column('kind', sa.String(20), nullable=False),
            sa.Column('hourly_rate', sa.Float(), nullable=False),
            sa.Column('monthly_fee', sa.Float(), nullable=False),
            sa.Column('included_hours', sa.Float(), nullable=False),
            sa.Column('per_device_fee', sa.Float(), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False),
            _timestamps())
        op.create_index('ix_contracts_org_id', 'contracts', ['org_id'])
        op.create_index('ix_contracts_customer_id', 'contracts', ['customer_id'])
    if 'invoices' not in existing:
        op.create_table('invoices',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
            sa.Column('period', sa.String(7), nullable=False),
            sa.Column('lines', sa.Text(), nullable=False),
            sa.Column('total', sa.Float(), nullable=False),
            sa.Column('proof_id', sa.String(32), nullable=False),
            _timestamps(),
            sa.UniqueConstraint('org_id', 'customer_id', 'period', name='uq_invoice_period'))
        op.create_index('ix_invoices_org_id', 'invoices', ['org_id'])
        op.create_index('ix_invoices_customer_id', 'invoices', ['customer_id'])
    if 'patch_policies' not in existing:
        op.create_table('patch_policies',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('auto_approve', sa.Text(), nullable=False),
            sa.Column('categories', sa.Text(), nullable=False),
            sa.Column('device_types', sa.Text(), nullable=False),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=True),
            sa.Column('window_days', sa.Text(), nullable=False),
            sa.Column('window_start_hour', sa.Integer(), nullable=False),
            sa.Column('window_end_hour', sa.Integer(), nullable=False),
            sa.Column('defer_days', sa.Integer(), nullable=False),
            sa.Column('reboot', sa.String(20), nullable=False),
            sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
            _timestamps())
        op.create_index('ix_patch_policies_org_id', 'patch_policies', ['org_id'])
    if 'alert_thresholds' not in existing:
        op.create_table('alert_thresholds',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('metric', sa.String(10), nullable=False),
            sa.Column('limit', sa.Float(), nullable=False),
            sa.Column('samples', sa.Integer(), nullable=False),
            sa.Column('severity', sa.String(20), nullable=False),
            sa.Column('device_type', sa.String(30), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            _timestamps())
        op.create_index('ix_alert_thresholds_org_id', 'alert_thresholds', ['org_id'])

    def columns(table):
        return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}

    # Batch mode rebuilds the table on SQLite; server defaults back-fill existing rows.
    if 'reboot_required' not in columns('devices'):
        with op.batch_alter_table('devices') as batch:
            batch.add_column(sa.Column('reboot_required', sa.Boolean(), nullable=False, server_default=sa.false()))
            batch.add_column(sa.Column('customer_id', sa.Integer(), nullable=True))
            batch.create_index('ix_devices_customer_id', ['customer_id'])
            batch.create_foreign_key('fk_devices_customer_id', 'customers', ['customer_id'], ['id'])
    if 'approval' not in columns('patches'):
        with op.batch_alter_table('patches') as batch:
            batch.add_column(sa.Column('approval', sa.String(20), nullable=False, server_default='unreviewed'))
            batch.create_index('ix_patches_approval', ['approval'])
    if 'customer_id' not in columns('tickets'):
        with op.batch_alter_table('tickets') as batch:
            batch.add_column(sa.Column('customer_id', sa.Integer(), nullable=True))
            batch.create_index('ix_tickets_customer_id', ['customer_id'])
            batch.create_foreign_key('fk_tickets_customer_id', 'customers', ['customer_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('tickets') as batch:
        batch.drop_constraint('fk_tickets_customer_id', type_='foreignkey')
        batch.drop_index('ix_tickets_customer_id')
        batch.drop_column('customer_id')
    with op.batch_alter_table('patches') as batch:
        batch.drop_index('ix_patches_approval')
        batch.drop_column('approval')
    with op.batch_alter_table('devices') as batch:
        batch.drop_constraint('fk_devices_customer_id', type_='foreignkey')
        batch.drop_index('ix_devices_customer_id')
        batch.drop_column('customer_id')
        batch.drop_column('reboot_required')
    for table in ('alert_thresholds', 'patch_policies', 'invoices', 'contracts', 'contacts', 'customers'):
        op.drop_table(table)
