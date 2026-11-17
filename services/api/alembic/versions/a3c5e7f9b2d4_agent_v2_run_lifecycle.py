"""Agent v2: record when a script run starts executing.

Revision ID: a3c5e7f9b2d4
Revises: f7b2d9e4a1c8
Create Date: 2026-11-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c5e7f9b2d4'
down_revision: Union[str, None] = 'f7b2d9e4a1c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'started_at' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('script_runs')}:
        with op.batch_alter_table('script_runs') as batch:
            batch.add_column(sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('script_runs') as batch:
        batch.drop_column('started_at')
