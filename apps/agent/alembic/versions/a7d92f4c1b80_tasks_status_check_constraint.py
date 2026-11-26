"""tasks_status_check_constraint

Revision ID: a7d92f4c1b80
Revises: f3b18c2d54a0
Create Date: 2026-11-25 01:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d92f4c1b80"
down_revision: str | Sequence[str] | None = "f3b18c2d54a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enforce valid task lifecycle statuses at the database level."""
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('queued', 'in_progress', 'awaiting_input', "
        "'completed', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    """Remove tasks.status check constraint."""
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
