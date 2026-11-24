"""GitHub Review Publisher with DiffHunkParser and 422 fallback (AC-5)."""

import logging
from dataclasses import dataclass

from app.application.ports.github_gateway import GitHubGateway
from app.application.services.diff_hunk_parser import DiffHunkParser

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishReviewResult:
    """Result of publishing a review to GitHub."""

    github_review_id: int | None
    inline_comments_count: int
    fallback_applied: bool
    summary_markdown: str


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
    ) -> PublishReviewResult:
        """Publish unified review with inline comments and automatic fallback."""
        file_diffs = DiffHunkParser.parse(diff_text)

        inline_comments: list[dict] = []
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

                # Reformat all inline findings into the summary narrative
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

        return PublishReviewResult(
            github_review_id=github_review_id,
            inline_comments_count=0 if fallback_applied else len(inline_comments),
            fallback_applied=fallback_applied,
            summary_markdown=final_summary,
        )
