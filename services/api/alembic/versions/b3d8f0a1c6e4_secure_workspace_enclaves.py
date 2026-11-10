"""secure workspace enclaves: policies, enclaves, events

Revision ID: b3d8f0a1c6e4
Revises: 2af1fe406df2
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d8f0a1c6e4'
down_revision: Union[str, None] = '2af1fe406df2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    # Non-production databases may already hold these tables via create_all().
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if 'enclave_policies' not in existing:
        op.create_table('enclave_policies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('allowed_apps', sa.Text(), nullable=False),
        sa.Column('blocked_apps', sa.Text(), nullable=False),
        sa.Column('network_allowlist', sa.Text(), nullable=False),
        sa.Column('dlp_rules', sa.Text(), nullable=False),
        sa.Column('clipboard_enabled', sa.Boolean(), nullable=False),
        sa.Column('watermark_enabled', sa.Boolean(), nullable=False),
        sa.Column('ai_governed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_enclave_policies_name'), 'enclave_policies', ['name'], unique=False)
        op.create_index(op.f('ix_enclave_policies_org_id'), 'enclave_policies', ['org_id'], unique=False)

    if 'secure_enclaves' not in existing:
        op.create_table('secure_enclaves',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('policy_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('encryption_key_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
        sa.ForeignKeyConstraint(['policy_id'], ['enclave_policies.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_secure_enclaves_device_id'), 'secure_enclaves', ['device_id'], unique=False)
        op.create_index(op.f('ix_secure_enclaves_org_id'), 'secure_enclaves', ['org_id'], unique=False)
        op.create_index(op.f('ix_secure_enclaves_status'), 'secure_enclaves', ['status'], unique=False)

    if 'enclave_events' not in existing:
        op.create_table('enclave_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('enclave_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.ForeignKeyConstraint(['enclave_id'], ['secure_enclaves.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_enclave_events_created_at'), 'enclave_events', ['created_at'], unique=False)
        op.create_index(op.f('ix_enclave_events_device_id'), 'enclave_events', ['device_id'], unique=False)
        op.create_index(op.f('ix_enclave_events_enclave_id'), 'enclave_events', ['enclave_id'], unique=False)
        op.create_index(op.f('ix_enclave_events_kind'), 'enclave_events', ['kind'], unique=False)
        op.create_index(op.f('ix_enclave_events_org_id'), 'enclave_events', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_table('enclave_events')
    op.drop_table('secure_enclaves')
    op.drop_table('enclave_policies')
