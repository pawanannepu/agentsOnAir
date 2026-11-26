"""task_interventions_and_transcripts

Revision ID: f3b18c2d54a0
Revises: e2a94519f802
Create Date: 2026-11-24 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3b18c2d54a0'
down_revision: Union[str, Sequence[str], None] = 'e2a94519f802'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema for live task streaming, human interventions, and transcripts."""
    # 1. Add interruption columns to tasks table
    op.add_column('tasks', sa.Column('interruption_prompt', sa.Text(), nullable=True))
    op.add_column('tasks', sa.Column('interruption_type', sa.String(length=50), nullable=True))
    op.add_column(
        'tasks',
        sa.Column('interruption_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'tasks',
        sa.Column('interruption_expires_at', sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Update partial unique index on tasks to include awaiting_input
    op.drop_index('uq_tasks_active_repo_issue', table_name='tasks')
    op.create_index(
        'uq_tasks_active_repo_issue',
        'tasks',
        ['repo_id', sa.text("(trigger_metadata->>'issue_number')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'in_progress', 'awaiting_input') AND deleted_at IS NULL"),
    )

    # 3. Create task_interventions table
    op.create_table(
        'task_interventions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('task_run_id', sa.UUID(), nullable=True),
        sa.Column('clerk_user_id', sa.String(length=255), nullable=False),
        sa.Column('intervention_type', sa.String(length=50), nullable=False),
        sa.Column('prompt_snapshot', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_run_id'], ['task_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_interventions_org_id', 'task_interventions', ['org_id'], unique=False)
    op.create_index('ix_task_interventions_task_id', 'task_interventions', ['task_id'], unique=False)
    op.create_index('ix_task_interventions_task_run_id', 'task_interventions', ['task_run_id'], unique=False)
    op.create_index('ix_task_interventions_clerk_user_id', 'task_interventions', ['clerk_user_id'], unique=False)
    op.create_index('ix_task_interventions_task_created', 'task_interventions', ['task_id', sa.text('created_at ASC')], unique=False)
    op.create_index('ix_task_interventions_org_created', 'task_interventions', ['org_id', sa.text('created_at DESC')], unique=False)

    # 4. Create task_transcripts table
    op.create_table(
        'task_transcripts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('task_run_id', sa.UUID(), nullable=False),
        sa.Column('terminal_log', sa.LargeBinary(), nullable=False),
        sa.Column('events_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('total_lines', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_run_id'], ['task_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_run_id'),
    )
    op.create_index('ix_task_transcripts_org_id', 'task_transcripts', ['org_id'], unique=False)
    op.create_index('ix_task_transcripts_task_id', 'task_transcripts', ['task_id'], unique=False)
    op.create_index('ix_task_transcripts_task_run_id', 'task_transcripts', ['task_run_id'], unique=True)
    op.create_index('ix_task_transcripts_task_created', 'task_transcripts', ['task_id', sa.text('created_at DESC')], unique=False)
    op.create_index('ix_task_transcripts_org_created', 'task_transcripts', ['org_id', sa.text('created_at DESC')], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('task_transcripts')
    op.drop_table('task_interventions')

    op.drop_index('uq_tasks_active_repo_issue', table_name='tasks')
    op.create_index(
        'uq_tasks_active_repo_issue',
        'tasks',
        ['repo_id', sa.text("(trigger_metadata->>'issue_number')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'in_progress') AND deleted_at IS NULL"),
    )

    op.drop_column('tasks', 'interruption_expires_at')
    op.drop_column('tasks', 'interruption_options')
    op.drop_column('tasks', 'interruption_type')
    op.drop_column('tasks', 'interruption_prompt')
