"""Integration tests for Alembic migration upgrade/downgrade (covers: AC-8)."""

from alembic.config import Config

from alembic import command


def test_alembic_migration_cycle():
    """Verify Alembic upgrade head -> downgrade base -> upgrade head cleanly."""
    cfg = Config("alembic.ini")

    # Run downgrade to base
    command.downgrade(cfg, "base")

    # Run upgrade to head
    command.upgrade(cfg, "head")

    # Downgrade again to base
    command.downgrade(cfg, "base")

    # Final upgrade to head
    command.upgrade(cfg, "head")
