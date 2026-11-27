"""guardrails_approvals_and_usage

Revision ID: b8e4c1d9a2f0
Revises: a7d92f4c1b80
Create Date: 2026-11-26 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b8e4c1d9a2f0"
down_revision: str | Sequence[str] | None = "a7d92f4c1b80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add paused_seconds, task_approvals, usage_events, and org_monthly_usage."""
    # 1. Add paused_seconds to task_runs
    op.add_column(
        "task_runs",
        sa.Column(
            "paused_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # 2. Create task_approvals table
    op.create_table(
        "task_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("task_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("risk_category", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("action_hash", sa.String(length=64), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column(
            "action_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_clerk_user_id", sa.String(length=255), nullable=True
        ),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_task_approvals_status",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_run_id"], ["task_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_approvals_org_id", "task_approvals", ["org_id"], unique=False
    )
    op.create_index(
        "ix_task_approvals_task_id", "task_approvals", ["task_id"], unique=False
    )
    op.create_index(
        "ix_task_approvals_task_run_id",
        "task_approvals",
        ["task_run_id"],
        unique=False,
    )
    op.create_index(
        "uq_task_approvals_pending_task",
        "task_approvals",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_task_approvals_task_created",
        "task_approvals",
        ["task_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_task_approvals_task_hash_status",
        "task_approvals",
        ["task_id", "action_hash", "status"],
        unique=False,
    )

    # 3. Create usage_events table
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("task_run_id", sa.UUID(), nullable=True),
        sa.Column("pr_review_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_cents", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation_type IN ('forge', 'reviewer', 'pr_review')",
            name="ck_usage_events_operation_type",
        ),
        sa.CheckConstraint(
            "task_run_id IS NOT NULL OR pr_review_id IS NOT NULL",
            name="ck_usage_events_parent_ref",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_run_id"], ["task_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pr_review_id"], ["pull_request_reviews.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_usage_events_org_created",
        "usage_events",
        ["org_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_task_run_created",
        "usage_events",
        ["task_run_id", sa.text("created_at ASC")],
        unique=False,
    )

    # 4. Create org_monthly_usage table
    op.create_table(
        "org_monthly_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("billing_month", sa.String(length=7), nullable=False),
        sa.Column(
            "total_tokens",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_cost_cents",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_org_monthly_usage_org_month",
        "org_monthly_usage",
        ["org_id", "billing_month"],
        unique=True,
    )


def downgrade() -> None:
    """Revert guardrails, approvals, and usage schema changes."""
    op.drop_table("org_monthly_usage")
    op.drop_table("usage_events")
    op.drop_table("task_approvals")
    op.drop_column("task_runs", "paused_seconds")
