"""Use cases for managing curated repository example pull requests."""

import re
import uuid
from datetime import UTC, datetime

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_examples_repository import ReviewExamplesRepository
from app.application.services.review_context_service import ReviewContextService
from app.domain.entities.review_example import ReviewExample
from app.domain.exceptions import ExternalServiceError, ValidationError

_PR_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+/[^/]+)/pull/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


def parse_example_pr_input(
    repo_full_name: str, pr_number: int | None, pr_url: str | None
) -> int:
    """Resolve and validate PR number from either pr_number or same-repo pr_url."""
    parsed_number: int | None = None
    if pr_url is not None and pr_url.strip():
        match = _PR_URL_RE.match(pr_url.strip())
        if not match:
            raise ValidationError(
                "Invalid GitHub pull request URL; expected https://github.com/<owner>/<repo>/pull/<number>"
            )
        url_repo, num_str = match.group(1), match.group(2)
        if url_repo.lower() != repo_full_name.lower():
            raise ValidationError(
                f"Pull request URL belongs to '{url_repo}', expected '{repo_full_name}'"
            )
        parsed_number = int(num_str)

    if (
        pr_number is not None
        and parsed_number is not None
        and pr_number != parsed_number
    ):
        raise ValidationError(
            f"pr_number ({pr_number}) does not match pr_url PR #{parsed_number}"
        )

    resolved = pr_number if pr_number is not None else parsed_number
    if resolved is None or resolved <= 0:
        raise ValidationError(
            "Either a positive pr_number or a valid pr_url is required"
        )
    return resolved


class ReviewExamplesUseCase:
    """Orchestrates attachment, GitHub verification, refresh, and deletion."""

    def __init__(
        self,
        examples_repo: ReviewExamplesRepository,
        repository_repo: RepositoryRepository,
        github_gateway: GitHubGateway,
        audit_log_repo: AuditLogRepository,
    ) -> None:
        self._examples_repo = examples_repo
        self._repository_repo = repository_repo
        self._github_gateway = github_gateway
        self._audit_log_repo = audit_log_repo

    async def list_examples(
        self, org_id: uuid.UUID, repo_id: uuid.UUID
    ) -> list[ReviewExample]:
        await self._repository_repo.get_by_id(org_id, repo_id)
        return await self._examples_repo.list_by_repo(org_id, repo_id)

    async def _fetch_and_summarize_pr(
        self, repo_full_name: str, installation_id: int, pr_number: int
    ) -> tuple[str, str, list[str], str, int, datetime]:
        try:
            token = await self._github_gateway.get_installation_token(installation_id)
            pr_data = await self._github_gateway.get_pull_request(
                repo_full_name, pr_number, token
            )
        except ValidationError:
            raise
        except ExternalServiceError as exc:
            raise ValidationError(
                f"Failed to fetch PR #{pr_number} from GitHub: {exc.message}"
            ) from exc
        except Exception as exc:
            raise ValidationError(
                f"Failed to fetch PR #{pr_number} from GitHub: {exc}"
            ) from exc

        base_repo = (pr_data.get("base") or {}).get("repo") or {}
        base_full_name = str(base_repo.get("full_name") or "").strip()
        if not base_full_name or base_full_name.lower() != repo_full_name.lower():
            raise ValidationError(
                f"Pull request #{pr_number} repository '{base_full_name or 'unknown'}' "
                f"does not match '{repo_full_name}'"
            )

        try:
            diff_text = await self._github_gateway.get_pull_request_diff(
                repo_full_name, pr_number, token
            )
        except ValidationError:
            raise
        except ExternalServiceError as exc:
            raise ValidationError(
                f"Failed to fetch diff for PR #{pr_number} from GitHub: {exc.message}"
            ) from exc
        except Exception as exc:
            raise ValidationError(
                f"Failed to fetch diff for PR #{pr_number} from GitHub: {exc}"
            ) from exc

        modified_files, summary, token_count = (
            ReviewContextService.build_diff_summary_and_files(
                diff_text, max_tokens=1500
            )
        )
        pr_url = str(
            pr_data.get("html_url")
            or f"https://github.com/{repo_full_name}/pull/{pr_number}"
        )
        pr_title = str(pr_data.get("title") or f"Pull Request #{pr_number}")[:512]
        now = datetime.now(UTC)
        return pr_url, pr_title, modified_files, summary, token_count, now

    async def create_example(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        actor_id: str,
        *,
        pr_number: int | None = None,
        pr_url: str | None = None,
        classification: str,
        guidance_note: str,
    ) -> ReviewExample:
        if classification not in ("good", "bad"):
            raise ValidationError("classification must be 'good' or 'bad'")
        clean_note = guidance_note.strip()
        if not clean_note:
            raise ValidationError("guidance_note must be non-empty")

        repo = await self._repository_repo.get_by_id(org_id, repo_id)
        resolved_pr_num = parse_example_pr_input(repo.full_name, pr_number, pr_url)

        (
            resolved_url,
            pr_title,
            modified_files,
            summary,
            token_count,
            cached_at,
        ) = await self._fetch_and_summarize_pr(
            repo.full_name, repo.github_installation_id, resolved_pr_num
        )

        created = await self._examples_repo.create_example(
            org_id=org_id,
            repo_id=repo_id,
            pr_number=resolved_pr_num,
            pr_url=resolved_url,
            pr_title=pr_title,
            classification=classification,
            guidance_note=clean_note,
            modified_files=modified_files,
            cached_diff_summary=summary,
            cached_token_count=token_count,
            cached_at=cached_at,
            created_by=actor_id,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_example.created",
            target_type="review_example",
            target_id=created.id,
            payload_after={
                "repo_id": str(repo_id),
                "pr_number": created.pr_number,
                "classification": created.classification,
                "modified_files": created.modified_files,
                "cached_token_count": created.cached_token_count,
            },
        )
        return created

    async def refresh_example(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        example_id: uuid.UUID,
        actor_id: str,
    ) -> ReviewExample:
        repo = await self._repository_repo.get_by_id(org_id, repo_id)
        existing = await self._examples_repo.get_by_id(org_id, repo_id, example_id)

        (
            resolved_url,
            pr_title,
            modified_files,
            summary,
            token_count,
            cached_at,
        ) = await self._fetch_and_summarize_pr(
            repo.full_name, repo.github_installation_id, existing.pr_number
        )

        refreshed = await self._examples_repo.update_cache(
            org_id=org_id,
            repo_id=repo_id,
            example_id=example_id,
            pr_url=resolved_url,
            pr_title=pr_title,
            modified_files=modified_files,
            cached_diff_summary=summary,
            cached_token_count=token_count,
            cached_at=cached_at,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_example.refreshed",
            target_type="review_example",
            target_id=refreshed.id,
            payload_before={"cached_token_count": existing.cached_token_count},
            payload_after={
                "modified_files": refreshed.modified_files,
                "cached_token_count": refreshed.cached_token_count,
            },
        )
        return refreshed

    async def delete_example(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        example_id: uuid.UUID,
        actor_id: str,
    ) -> None:
        await self._repository_repo.get_by_id(org_id, repo_id)
        deleted = await self._examples_repo.delete_example(org_id, repo_id, example_id)
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_example.deleted",
            target_type="review_example",
            target_id=deleted.id,
            payload_before={
                "repo_id": str(repo_id),
                "pr_number": deleted.pr_number,
                "classification": deleted.classification,
            },
        )
