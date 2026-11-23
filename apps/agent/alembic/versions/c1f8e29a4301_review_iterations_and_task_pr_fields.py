"""review_iterations_and_task_pr_fields

Revision ID: c1f8e29a4301
Revises: 962c4939d517
Create Date: 2026-11-22 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1f8e29a4301'
down_revision: Union[str, Sequence[str], None] = '962c4939d517'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add new columns to tasks
    op.add_column('tasks', sa.Column('base_branch', sa.String(length=100), server_default='main', nullable=False))
    op.add_column('tasks', sa.Column('pr_url', sa.String(length=512), nullable=True))
    op.add_column('tasks', sa.Column('head_commit_sha', sa.String(length=40), nullable=True))
    op.add_column('tasks', sa.Column('pr_review_status', sa.String(length=50), nullable=True))

    # 2. Add partial unique index on tasks for active repo + issue
    op.create_index(
        'uq_tasks_active_repo_issue',
        'tasks',
        ['repo_id', sa.text("(trigger_metadata->>'issue_number')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'in_progress') AND deleted_at IS NULL")
    )

    # 3. Create review_iterations table
    op.create_table(
        'review_iterations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('task_run_id', sa.UUID(), nullable=False),
        sa.Column('cycle_number', sa.Integer(), nullable=False),
        sa.Column('verdict', sa.String(length=50), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('blocking_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('non_blocking_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('diff_snapshot', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['task_run_id'], ['task_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_iterations_org_id'), 'review_iterations', ['org_id'], unique=False)
    op.create_index(op.f('ix_review_iterations_task_run_id'), 'review_iterations', ['task_run_id'], unique=False)
    op.create_index('ix_review_iterations_run_cycle', 'review_iterations', ['task_run_id', 'cycle_number'], unique=False)
    op.create_index('ix_review_iterations_org_created', 'review_iterations', ['org_id', sa.literal_column('created_at DESC')], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_review_iterations_org_created', table_name='review_iterations')
    op.drop_index('ix_review_iterations_run_cycle', table_name='review_iterations')
    op.drop_index(op.f('ix_review_iterations_task_run_id'), table_name='review_iterations')
    op.drop_index(op.f('ix_review_iterations_org_id'), table_name='review_iterations')
    op.drop_table('review_iterations')

    op.drop_index('uq_tasks_active_repo_issue', table_name='tasks')
    op.drop_column('tasks', 'pr_review_status')
    op.drop_column('tasks', 'head_commit_sha')
    op.drop_column('tasks', 'pr_url')
    op.drop_column('tasks', 'base_branch')
