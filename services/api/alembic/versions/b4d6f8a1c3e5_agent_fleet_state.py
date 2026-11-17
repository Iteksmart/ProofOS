"""Agent fleet management: lockdown, spool and server execution policy per endpoint.

Revision ID: b4d6f8a1c3e5
Revises: a3c5e7f9b2d4
Create Date: 2026-11-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4d6f8a1c3e5'
down_revision: Union[str, None] = 'a3c5e7f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ('agent_locked', sa.Boolean(), sa.false()),
    ('agent_spooled', sa.Integer(), sa.text('0')),
    ('agent_exec_enabled', sa.Boolean(), sa.true()),
)


def upgrade() -> None:
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('devices')}
    with op.batch_alter_table('devices') as batch:
        for name, kind, default in COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, kind, nullable=False, server_default=default))


def downgrade() -> None:
    with op.batch_alter_table('devices') as batch:
        for name, _, _ in COLUMNS:
            batch.drop_column(name)
