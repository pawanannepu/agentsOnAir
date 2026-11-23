"""SQLAlchemy task repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_repository import TaskRepository
from app.domain.entities.task import Task
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.task import TaskModel


def _to_entity(model: TaskModel) -> Task:
    return Task(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        title=model.title,
        description=model.description,
        status=model.status,
        trigger_type=model.trigger_type,
        trigger_metadata=model.trigger_metadata or {},
        base_branch=model.base_branch,
        branch_name=model.branch_name,
        pr_number=model.pr_number,
        pr_url=model.pr_url,
        head_commit_sha=model.head_commit_sha,
        pr_review_status=model.pr_review_status,
        created_by_clerk_user_id=model.created_by_clerk_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        deleted_at=model.deleted_at,
    )


class SqlAlchemyTaskRepository(TaskRepository):
    """Async SQLAlchemy adapter for Task persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_task(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        title: str,
        description: str,
        trigger_type: str,
        trigger_metadata: dict | None = None,
        base_branch: str = "main",
        branch_name: str | None = None,
        created_by_clerk_user_id: str | None = None,
    ) -> Task:
        # Validate repository belongs to this org
        repo_stmt = select(RepositoryModel).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.id == repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        repo = (await self._session.execute(repo_stmt)).scalar_one_or_none()
        if not repo:
            raise NotFoundError(
                f"Repository {repo_id} not found in tenant organization"
            )

        model = TaskModel(
            org_id=org_id,
            repo_id=repo_id,
            title=title,
            description=description,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata or {},
            base_branch=base_branch,
            branch_name=branch_name,
            created_by_clerk_user_id=created_by_clerk_user_id,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def find_active_by_repo_and_issue(
        self, repo_id: uuid.UUID, issue_number: int
    ) -> Task | None:
        stmt = select(TaskModel).where(
            TaskModel.repo_id == repo_id,
            TaskModel.status.in_(["queued", "in_progress"]),
            TaskModel.deleted_at.is_(None),
            TaskModel.trigger_metadata["issue_number"].astext == str(issue_number),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def get_by_id(self, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        stmt = select(TaskModel).where(
            TaskModel.org_id == org_id,
            TaskModel.id == task_id,
            TaskModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Task {task_id} not found in tenant organization")
        return _to_entity(model)

    async def list_by_repo(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Task], int]:
        count_stmt = select(func.count(TaskModel.id)).where(
            TaskModel.org_id == org_id,
            TaskModel.repo_id == repo_id,
            TaskModel.deleted_at.is_(None),
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        offset = max(0, (page - 1) * page_size)
        list_stmt = (
            select(TaskModel)
            .where(
                TaskModel.org_id == org_id,
                TaskModel.repo_id == repo_id,
                TaskModel.deleted_at.is_(None),
            )
            .order_by(TaskModel.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(list_stmt)).scalars().all()
        return [_to_entity(m) for m in models], total

    async def update_status(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        status: str,
        branch_name: str | None = None,
        pr_number: int | None = None,
    ) -> Task:
        stmt = select(TaskModel).where(
            TaskModel.org_id == org_id,
            TaskModel.id == task_id,
            TaskModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Task {task_id} not found in tenant organization")

        model.status = status
        if branch_name is not None:
            model.branch_name = branch_name
        if pr_number is not None:
            model.pr_number = pr_number
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _to_entity(model)

    async def soft_delete(self, org_id: uuid.UUID, task_id: uuid.UUID) -> None:
        stmt = select(TaskModel).where(
            TaskModel.org_id == org_id,
            TaskModel.id == task_id,
            TaskModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Task {task_id} not found in tenant organization")

        model.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def update_pr_details(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        pr_url: str,
        head_commit_sha: str,
        pr_review_status: str,
        pr_number: int | None = None,
        branch_name: str | None = None,
    ) -> Task:
        stmt = select(TaskModel).where(
            TaskModel.org_id == org_id,
            TaskModel.id == task_id,
            TaskModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Task {task_id} not found in tenant organization")

        model.pr_url = pr_url
        model.head_commit_sha = head_commit_sha
        model.pr_review_status = pr_review_status
        if pr_number is not None:
            model.pr_number = pr_number
        if branch_name is not None:
            model.branch_name = branch_name
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _to_entity(model)
