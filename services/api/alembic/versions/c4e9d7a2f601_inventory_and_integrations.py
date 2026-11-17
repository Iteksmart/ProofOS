"""Persist endpoint inventory and tenant integration credentials."""
from alembic import op
import sqlalchemy as sa

revision = "c4e9d7a2f601"
down_revision = "a7c1e5b9d2f3"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "device_inventory" not in existing:
        op.create_table("device_inventory",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_device_inventory_org_id", "device_inventory", ["org_id"])
        op.create_index("ix_device_inventory_device_id", "device_inventory", ["device_id"], unique=True)
        op.create_index("ix_device_inventory_collected_at", "device_inventory", ["collected_at"])
    if "integration_connections" not in existing:
        op.create_table("integration_connections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("provider", sa.String(30), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("received_count", sa.Integer(), nullable=False),
            sa.Column("last_received_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_integration_connections_org_id", "integration_connections", ["org_id"])
    if "integration_alert_links" not in existing:
        op.create_table("integration_alert_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("connection_id", sa.Integer(), sa.ForeignKey("integration_connections.id"), nullable=False),
            sa.Column("external_key", sa.String(64), nullable=False),
            sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.UniqueConstraint("connection_id", "external_key", name="uq_integration_alert_key"))
        op.create_index("ix_integration_alert_links_org_id", "integration_alert_links", ["org_id"])


def downgrade():
    op.drop_table("integration_alert_links")
    op.drop_table("integration_connections")
    op.drop_table("device_inventory")
