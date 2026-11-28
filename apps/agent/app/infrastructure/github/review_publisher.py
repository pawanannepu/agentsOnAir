"""GitHub Review Publisher with DiffHunkParser, 422 fallback, and comment backfill."""

import logging
import uuid
from dataclasses import dataclass, field

from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.pr_review_repository import PRReviewRepository
from app.application.services.diff_hunk_parser import DiffHunkParser

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishReviewResult:
    """Result of publishing a review to GitHub."""

    github_review_id: int | None
    inline_comments_count: int
    fallback_applied: bool
    summary_markdown: str
    comment_id_mappings: list[tuple[uuid.UUID, int]] = field(default_factory=list)


class GitHubReviewPublisher:
    """Formats and submits PR reviews with automatic 422 line drift fallback."""

    def __init__(self, github_gateway: GitHubGateway) -> None:
        self._github_gateway = github_gateway

    def format_suggestion(self, finding: dict) -> str:
        """Format inline comment with GitHub markdown suggestion block."""
        sev = finding["severity"].upper()
        title = finding["title"]
        msg = finding["message"]
        body = f"**[{sev}] {title}**\n\n{msg}"
        if finding.get("suggested_patch"):
            patch = finding["suggested_patch"].strip()
            body += f"\n\n```suggestion\n{patch}\n```"
        return body

    def format_out_of_diff_permalink(
        self,
        repo_full_name: str,
        commit_sha: str,
        finding: dict,
    ) -> str:
        """Format cross-file/architectural finding as permalink in summary narrative."""
        file_path = finding["file_path"]
        line_num = finding["line_number"]
        permalink = f"https://github.com/{repo_full_name}/blob/{commit_sha}/{file_path}#L{line_num}"
        sev = finding["severity"].upper()
        cat = finding["category"]
        title = finding["title"]
        return f"- **[{sev}] [{cat}] [{title}]({permalink})**\n  {finding['message']}"

    async def publish(
        self,
        repo_full_name: str,
        pr_number: int,
        head_commit_sha: str,
        verdict: str,
        summary: str,
        findings: list[dict],
        diff_text: str,
        token: str,
        pr_review_repo: PRReviewRepository | None = None,
    ) -> PublishReviewResult:
        """Publish unified review with inline comments and automatic fallback."""
        file_diffs = DiffHunkParser.parse(diff_text)

        inline_comments: list[dict] = []
        inline_finding_ids: list[uuid.UUID | None] = []
        out_of_diff_findings: list[dict] = []

        # Categorize findings: in diff hunks vs out of diff
        for f in findings:
            file_path = f["file_path"]
            line_num = f["line_number"]
            fdiff = file_diffs.get(file_path)

            if fdiff and fdiff.contains_new_line(line_num):
                inline_comments.append(
                    {
                        "path": file_path,
                        "line": line_num,
                        "side": f.get("side", "RIGHT"),
                        "body": self.format_suggestion(f),
                    }
                )
                fid = f.get("id")
                if isinstance(fid, str):
                    try:
                        fid = uuid.UUID(fid)
                    except ValueError:
                        fid = None
                inline_finding_ids.append(fid if isinstance(fid, uuid.UUID) else None)
            else:
                out_of_diff_findings.append(f)

        # Assemble summary markdown with permalinks for out of diff findings
        final_summary_parts = [summary]
        if out_of_diff_findings:
            final_summary_parts.append("\n### Architectural & Cross-File Findings\n")
            for ood in out_of_diff_findings:
                final_summary_parts.append(
                    self.format_out_of_diff_permalink(
                        repo_full_name, head_commit_sha, ood
                    )
                )

        final_summary = "\n".join(final_summary_parts)

        # Map domain verdict to GitHub review event
        github_event = "COMMENT"
        if verdict == "approved":
            github_event = "APPROVE"
        elif verdict == "changes_requested":
            github_event = "REQUEST_CHANGES"

        fallback_applied = False
        github_review_id: int | None = None

        try:
            review_resp = await self._github_gateway.submit_review(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                commit_sha=head_commit_sha,
                body=final_summary,
                event=github_event,
                comments=inline_comments,
                token=token,
            )
            github_review_id = review_resp.get("id")
        except Exception as exc:
            # AC-5: If GitHub returns 422 line drift error, fall back to summary only
            err_msg = str(exc)
            if "422" in err_msg or "Unprocessable" in err_msg:
                fallback_applied = True
                logger.warning(
                    "GitHub review rejected with 422 diff drift. Fallback to summary."
                )

                fallback_summary_parts = [
                    final_summary,
                    "\n### Inline Findings (Diff Drift Fallback)\n",
                ]
                for f in inline_comments:
                    fallback_summary_parts.append(
                        f"- `{f['path']}:{f['line']}`:\n{f['body']}\n"
                    )
                fallback_summary = "\n".join(fallback_summary_parts)

                review_resp = await self._github_gateway.submit_review(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    commit_sha=head_commit_sha,
                    body=fallback_summary,
                    event=github_event,
                    comments=[],
                    token=token,
                )
                github_review_id = review_resp.get("id")
                final_summary = fallback_summary
            else:
                raise

        comment_id_mappings: list[tuple[uuid.UUID, int]] = []
        if inline_comments and not fallback_applied and github_review_id is not None:
            try:
                remote_comments = await self._github_gateway.list_review_comments(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    github_review_id=int(github_review_id),
                    token=token,
                )
                used_indices: set[int] = set()
                for idx, local_comment in enumerate(inline_comments):
                    fid = inline_finding_ids[idx]
                    if fid is None:
                        continue
                    local_key = (
                        local_comment["path"],
                        local_comment["line"],
                        local_comment["body"],
                    )
                    for r_idx, rc in enumerate(remote_comments):
                        if r_idx in used_indices:
                            continue
                        r_line = rc.get("line")
                        if r_line is None:
                            r_line = rc.get("original_line")
                        remote_key = (
                            rc.get("path"),
                            r_line,
                            rc.get("body"),
                        )
                        if remote_key == local_key and rc.get("id") is not None:
                            used_indices.add(r_idx)
                            cid = int(rc["id"])
                            comment_id_mappings.append((fid, cid))
                            if pr_review_repo is not None:
                                await pr_review_repo.update_finding_github_id(fid, cid)
                            break
            except Exception as exc:
                logger.warning(
                    "Failed to backfill GitHub comment IDs for review %s: %s",
                    github_review_id,
                    exc,
                )

        return PublishReviewResult(
            github_review_id=github_review_id,
            inline_comments_count=0 if fallback_applied else len(inline_comments),
            fallback_applied=fallback_applied,
            summary_markdown=final_summary,
            comment_id_mappings=comment_id_mappings,
        )
