"""Proof anchors, vulnerability findings, service SLOs, customer portal links,
and ticket requester email.

Revision ID: f7b2d9e4a1c8
Revises: e5a9c3b71d20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7b2d9e4a1c8'
down_revision: Union[str, None] = 'e5a9c3b71d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'proof_anchors' not in existing:
        op.create_table('proof_anchors',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('chain_head', sa.String(64), nullable=False),
            sa.Column('last_record_id', sa.String(32), nullable=False),
            sa.Column('record_count', sa.Integer(), nullable=False),
            sa.Column('imprint', sa.String(64), nullable=False),
            sa.Column('tsa_url', sa.String(500), nullable=False),
            sa.Column('token', sa.Text(), nullable=False),
            sa.Column('gen_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_proof_anchors_chain_head', 'proof_anchors', ['chain_head'])
        op.create_index('ix_proof_anchors_created_at', 'proof_anchors', ['created_at'])
    if 'vulnerability_findings' not in existing:
        op.create_table('vulnerability_findings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id'), nullable=False),
            sa.Column('package', sa.String(255), nullable=False),
            sa.Column('version', sa.String(255), nullable=False),
            sa.Column('ecosystem', sa.String(100), nullable=False),
            sa.Column('vuln_id', sa.String(100), nullable=False),
            sa.Column('aliases', sa.Text(), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('severity', sa.String(20), nullable=False),
            sa.Column('fixed_version', sa.String(255), nullable=False),
            sa.Column('status', sa.String(20), nullable=False),
            sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('device_id', 'vuln_id', 'package', name='uq_vuln_device_package'))
        for column in ('org_id', 'device_id', 'vuln_id', 'severity', 'status'):
            op.create_index(f'ix_vulnerability_findings_{column}', 'vulnerability_findings', [column])
    if 'service_slos' not in existing:
        op.create_table('service_slos',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('service', sa.String(255), nullable=False),
            sa.Column('max_error_rate', sa.Float(), nullable=False),
            sa.Column('max_p95_ms', sa.Float(), nullable=False),
            sa.Column('window_minutes', sa.Integer(), nullable=False),
            sa.Column('min_requests', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('org_id', 'service', name='uq_slo_org_service'))
        op.create_index('ix_service_slos_org_id', 'service_slos', ['org_id'])
    if 'portal_links' not in existing:
        op.create_table('portal_links',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
            sa.Column('contact_email', sa.String(255), nullable=False),
            sa.Column('token_hash', sa.String(64), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('revoked', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_portal_links_org_id', 'portal_links', ['org_id'])
        op.create_index('ix_portal_links_customer_id', 'portal_links', ['customer_id'])
        op.create_index('ix_portal_links_token_hash', 'portal_links', ['token_hash'], unique=True)
    if 'requester_email' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('tickets')}:
        with op.batch_alter_table('tickets') as batch:
            batch.add_column(sa.Column('requester_email', sa.String(255), nullable=False, server_default=''))
            batch.create_index('ix_tickets_requester_email', ['requester_email'])
    if 'public' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('ticket_comments')}:
        with op.batch_alter_table('ticket_comments') as batch:
            batch.add_column(sa.Column('public', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('ticket_comments') as batch:
        batch.drop_column('public')
    with op.batch_alter_table('tickets') as batch:
        batch.drop_index('ix_tickets_requester_email')
        batch.drop_column('requester_email')
    for table in ('portal_links', 'service_slos', 'vulnerability_findings', 'proof_anchors'):
        op.drop_table(table)
