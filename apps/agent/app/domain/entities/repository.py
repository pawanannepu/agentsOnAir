"""Repository domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Repository:
    """Synchronized GitHub repository entity."""

    id: uuid.UUID
    org_id: uuid.UUID
    github_repo_id: int
    github_installation_id: int
    name: str
    full_name: str
    default_branch: str = "main"
    is_private: bool = True
    config: dict = field(default_factory=dict)
    review_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "auto_review": True,
            "allow_approval": False,
            "ignore_all_bots": False,
            "min_severity": "info",
            "max_comments": 25,
            "ignored_paths": ["*.lock", "dist/**", "node_modules/**"],
        }
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
