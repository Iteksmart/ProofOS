"""Service topology, telemetry, access grants and recovery evidence."""
from alembic import op
import sqlalchemy as sa

revision = "d8f6a204b913"
down_revision = "c4e9d7a2f601"
branch_labels = None
depends_on = None


def upgrade():
    # Frozen table definitions: do not import runtime models into migrations.
    definitions = {
        "service_nodes": [sa.Column("name", sa.String(255), nullable=False), sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id")), sa.Column("description", sa.Text(), nullable=False), sa.UniqueConstraint("org_id", "name", name="uq_service_org_name")],
        "service_dependencies": [sa.Column("source_id", sa.Integer(), sa.ForeignKey("service_nodes.id"), nullable=False), sa.Column("target_id", sa.Integer(), sa.ForeignKey("service_nodes.id"), nullable=False), sa.Column("origin", sa.String(30), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("org_id", "source_id", "target_id", name="uq_service_dependency")],
        "telemetry_events": [sa.Column("kind", sa.String(10), nullable=False), sa.Column("service", sa.String(255), nullable=False), sa.Column("trace_id", sa.String(32), nullable=False), sa.Column("span_id", sa.String(16), nullable=False), sa.Column("parent_span_id", sa.String(16), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("severity", sa.String(30), nullable=False), sa.Column("body", sa.Text(), nullable=False), sa.Column("duration_ms", sa.Float(), nullable=False), sa.Column("attributes", sa.Text(), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("received_at", sa.DateTime(timezone=True), nullable=False)],
        "access_grants": [sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("approver_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("capability", sa.String(30), nullable=False), sa.Column("target_id", sa.Integer(), nullable=False), sa.Column("command", sa.Text(), nullable=False), sa.Column("reason", sa.String(1000), nullable=False), sa.Column("minutes", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)],
        "recovery_policies": [sa.Column("run_id", sa.Integer(), sa.ForeignKey("script_runs.id"), nullable=False), sa.Column("kind", sa.String(10), nullable=False), sa.Column("target", sa.String(1000), nullable=False), sa.Column("expected_status", sa.Integer(), nullable=False), sa.Column("max_latency_ms", sa.Float(), nullable=False), sa.Column("samples_required", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("run_id")],
        "recovery_observations": [sa.Column("policy_id", sa.Integer(), sa.ForeignKey("recovery_policies.id"), nullable=False), sa.Column("payload", sa.Text(), nullable=False), sa.Column("proof_id", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)],
    }
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name, columns in definitions.items():
        if name in existing:
            continue
        op.create_table(name, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False), *columns)
        op.create_index(f"ix_{name}_org_id", name, ["org_id"])
        for column in {"telemetry_events": ["kind", "service", "trace_id", "received_at"], "recovery_observations": ["policy_id"]}.get(name, []):
            op.create_index(f"ix_{name}_{column}", name, [column])


def downgrade():
    for name in ["recovery_observations", "recovery_policies", "access_grants", "telemetry_events", "service_dependencies", "service_nodes"]:
        op.drop_table(name)
