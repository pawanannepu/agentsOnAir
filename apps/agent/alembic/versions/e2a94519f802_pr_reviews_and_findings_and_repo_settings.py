"""pr_reviews_and_findings_and_repo_settings

Revision ID: e2a94519f802
Revises: c1f8e29a4301
Create Date: 2026-11-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e2a94519f802'
down_revision: Union[str, Sequence[str], None] = 'c1f8e29a4301'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add review_settings JSONB column to repositories
    op.add_column(
        'repositories',
        sa.Column(
            'review_settings',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'{"enabled": true, "auto_review": true, "allow_approval": false, "ignore_all_bots": false, "min_severity": "info", "max_comments": 25, "ignored_paths": ["*.lock", "dist/**", "node_modules/**"]}\'::jsonb'
            ),
            nullable=False,
        )
    )

    # 2. Create pull_request_reviews table
    op.create_table(
        'pull_request_reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('repo_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=True),
        sa.Column('pr_number', sa.Integer(), nullable=False),
        sa.Column('pr_title', sa.String(length=512), nullable=False),
        sa.Column('pr_author', sa.String(length=100), nullable=False),
        sa.Column('head_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('base_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('verdict', sa.String(length=50), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('github_review_id', sa.BigInteger(), nullable=True),
        sa.Column('context_token_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('execution_duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pull_request_reviews_org_id'), 'pull_request_reviews', ['org_id'], unique=False)
    op.create_index(op.f('ix_pull_request_reviews_repo_id'), 'pull_request_reviews', ['repo_id'], unique=False)
    op.create_index(
        'ix_pr_reviews_repo_pr_created',
        'pull_request_reviews',
        ['repo_id', 'pr_number', sa.literal_column('created_at DESC')],
        unique=False
    )
    op.create_index(
        'ix_pr_reviews_org_created',
        'pull_request_reviews',
        ['org_id', sa.literal_column('created_at DESC')],
        unique=False
    )
    op.create_index(
        'uq_pr_reviews_active_pr',
        'pull_request_reviews',
        ['repo_id', 'pr_number'],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'analyzing', 'reviewing', 'posting')")
    )

    # 3. Create pr_review_findings table
    op.create_table(
        'pr_review_findings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('review_id', sa.UUID(), nullable=False),
        sa.Column('file_path', sa.String(length=1024), nullable=False),
        sa.Column('start_line', sa.Integer(), nullable=True),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('side', sa.String(length=10), server_default='RIGHT', nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('suggested_patch', sa.Text(), nullable=True),
        sa.Column('github_comment_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='open', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['review_id'], ['pull_request_reviews.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pr_review_findings_review_id'), 'pr_review_findings', ['review_id'], unique=False)
    op.create_index('ix_pr_findings_review_severity', 'pr_review_findings', ['review_id', 'severity'], unique=False)
    op.create_index('ix_pr_findings_review_file', 'pr_review_findings', ['review_id', 'file_path'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_pr_findings_review_file', table_name='pr_review_findings')
    op.drop_index('ix_pr_findings_review_severity', table_name='pr_review_findings')
    op.drop_index(op.f('ix_pr_review_findings_review_id'), table_name='pr_review_findings')
    op.drop_table('pr_review_findings')

    op.drop_index('uq_pr_reviews_active_pr', table_name='pull_request_reviews')
    op.drop_index('ix_pr_reviews_org_created', table_name='pull_request_reviews')
    op.drop_index('ix_pr_reviews_repo_pr_created', table_name='pull_request_reviews')
    op.drop_index(op.f('ix_pull_request_reviews_repo_id'), table_name='pull_request_reviews')
    op.drop_index(op.f('ix_pull_request_reviews_org_id'), table_name='pull_request_reviews')
    op.drop_table('pull_request_reviews')

    op.drop_column('repositories', 'review_settings')
