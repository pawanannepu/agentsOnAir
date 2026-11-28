"""custom_review_rules_and_feedback_learning

Revision ID: c4f9a2e1d803
Revises: b8e4c1d9a2f0
Create Date: 2026-11-28 02:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4f9a2e1d803"
down_revision: str | Sequence[str] | None = "b8e4c1d9a2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create Spec 0009 review rules, overrides, examples, feedback, and analytics indexes."""
    # 1. review_rules
    op.create_table(
        "review_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column(
            "path_globs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[\"**/*\"]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'major', 'minor', 'info')",
            name="ck_review_rules_severity",
        ),
        sa.CheckConstraint(
            "category IN ('security', 'bug', 'performance', 'architecture', 'style')",
            name="ck_review_rules_category",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_rules_org_repo_enabled_active",
        "review_rules",
        ["org_id", "repo_id", "is_enabled"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 2. review_rule_overrides
    op.create_table(
        "review_rule_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=True),
        sa.Column("severity_override", sa.String(length=20), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity_override IS NULL OR severity_override IN "
            "('critical', 'major', 'minor', 'info')",
            name="ck_review_rule_overrides_severity",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["review_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_review_rule_overrides_repo_rule",
        "review_rule_overrides",
        ["repo_id", "rule_id"],
        unique=True,
    )
    op.create_index(
        "ix_review_rule_overrides_org_id",
        "review_rule_overrides",
        ["org_id"],
        unique=False,
    )

    # 3. review_examples
    op.create_table(
        "review_examples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("pr_url", sa.String(length=512), nullable=False),
        sa.Column("pr_title", sa.String(length=512), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=False),
        sa.Column("guidance_note", sa.Text(), nullable=False),
        sa.Column(
            "modified_files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("cached_diff_summary", sa.Text(), nullable=True),
        sa.Column(
            "cached_token_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "classification IN ('good', 'bad')",
            name="ck_review_examples_classification",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_review_examples_repo_pr",
        "review_examples",
        ["repo_id", "pr_number"],
        unique=True,
    )
    op.create_index(
        "ix_review_examples_org_repo",
        "review_examples",
        ["org_id", "repo_id"],
        unique=False,
    )

    # 4. Extend pr_review_findings
    op.add_column(
        "pr_review_findings",
        sa.Column("rule_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "pr_review_findings",
        sa.Column(
            "feedback_state",
            sa.String(length=20),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_pr_review_findings_rule_id",
        "pr_review_findings",
        "review_rules",
        ["rule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_pr_review_findings_feedback_state",
        "pr_review_findings",
        "feedback_state IN ('none', 'accepted', 'dismissed')",
    )
    op.create_index(
        "ix_pr_findings_rule_feedback",
        "pr_review_findings",
        ["rule_id", "feedback_state"],
        unique=False,
    )
    op.create_index(
        "ix_pr_findings_review_feedback",
        "pr_review_findings",
        ["review_id", "feedback_state"],
        unique=False,
    )
    op.create_index(
        "ix_pr_findings_github_comment_id",
        "pr_review_findings",
        ["github_comment_id"],
        unique=False,
        postgresql_where=sa.text("github_comment_id IS NOT NULL"),
    )

    # 5. review_finding_feedback (append-only)
    op.create_table(
        "review_finding_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("feedback_type", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "remember_preference",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("github_event_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feedback_type IN ('accepted', 'dismissed')",
            name="ck_review_finding_feedback_type",
        ),
        sa.CheckConstraint(
            "source IN ('console', 'github_thread_resolved', 'github_comment_reply')",
            name="ck_review_finding_feedback_source",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["finding_id"], ["pr_review_findings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_review_finding_feedback_gh_event",
        "review_finding_feedback",
        ["github_event_id"],
        unique=True,
        postgresql_where=sa.text("github_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_review_finding_feedback_finding_created",
        "review_finding_feedback",
        ["finding_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_review_finding_feedback_org_repo",
        "review_finding_feedback",
        ["org_id", "repo_id"],
        unique=False,
    )

    # 6. review_learned_preferences
    op.create_table(
        "review_learned_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=True),
        sa.Column("source_feedback_id", sa.UUID(), nullable=True),
        sa.Column("pattern_key", sa.String(length=255), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column(
            "dismiss_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "accept_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_dismissals",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("last_feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'dampened', 'suppressed')",
            name="ck_review_learned_prefs_status",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["review_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_feedback_id"],
            ["review_finding_feedback.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_review_learned_prefs_repo_pattern",
        "review_learned_preferences",
        ["repo_id", "pattern_key"],
        unique=True,
    )
    op.create_index(
        "ix_review_learned_prefs_org_repo_status",
        "review_learned_preferences",
        ["org_id", "repo_id", "status"],
        unique=False,
    )

    # 7. Analytics composite indexes on existing tables
    op.create_index(
        "ix_pr_reviews_org_status_created",
        "pull_request_reviews",
        ["org_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_pr_reviews_repo_status_created",
        "pull_request_reviews",
        ["repo_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_runs_org_status_completed",
        "task_runs",
        ["org_id", "status", "completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_pr_review_created",
        "usage_events",
        ["pr_review_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Revert Spec 0009 tables, columns, and analytics indexes."""
    op.drop_index("ix_usage_events_pr_review_created", table_name="usage_events")
    op.drop_index("ix_task_runs_org_status_completed", table_name="task_runs")
    op.drop_index(
        "ix_pr_reviews_repo_status_created", table_name="pull_request_reviews"
    )
    op.drop_index(
        "ix_pr_reviews_org_status_created", table_name="pull_request_reviews"
    )

    op.drop_table("review_learned_preferences")
    op.drop_table("review_finding_feedback")

    op.drop_index(
        "ix_pr_findings_github_comment_id", table_name="pr_review_findings"
    )
    op.drop_index("ix_pr_findings_review_feedback", table_name="pr_review_findings")
    op.drop_index("ix_pr_findings_rule_feedback", table_name="pr_review_findings")
    op.drop_constraint(
        "ck_pr_review_findings_feedback_state",
        "pr_review_findings",
        type_="check",
    )
    op.drop_constraint(
        "fk_pr_review_findings_rule_id",
        "pr_review_findings",
        type_="foreignkey",
    )
    op.drop_column("pr_review_findings", "feedback_state")
    op.drop_column("pr_review_findings", "rule_id")

    op.drop_table("review_examples")
    op.drop_table("review_rule_overrides")
    op.drop_table("review_rules")
