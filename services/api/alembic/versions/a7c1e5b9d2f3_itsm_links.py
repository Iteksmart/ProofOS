"""itsm_links: map iTechSmart ITSM tickets to ProofOS tickets

Revision ID: a7c1e5b9d2f3
Revises: b3d8f0a1c6e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7c1e5b9d2f3'
down_revision: Union[str, None] = 'b3d8f0a1c6e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'itsm_links',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('org_id', sa.Integer(), sa.ForeignKey('orgs.id'), nullable=False),
        sa.Column('itsm_id', sa.String(40), nullable=False),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id'), nullable=False),
        sa.Column('itsm_status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('itsm_updated_at', sa.String(40), nullable=False, server_default=''),
        sa.Column('receipt_id', sa.String(80), nullable=False, server_default=''),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'itsm_id', name='uq_itsm_links_org_itsm'),
    )
    op.create_index('ix_itsm_links_org_id', 'itsm_links', ['org_id'])
    op.create_index('ix_itsm_links_itsm_id', 'itsm_links', ['itsm_id'])
    op.create_index('ix_itsm_links_ticket_id', 'itsm_links', ['ticket_id'])


def downgrade() -> None:
    op.drop_table('itsm_links')
