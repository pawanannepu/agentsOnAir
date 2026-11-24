# Verify: Full repository context code reviewer · spec 0005 · updated 2026-11-24
_Steps derived from spec 0005 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [x] Post a GitHub pull request event webhook (`pull_request.opened`) with valid HMAC SHA256 header → review record queued in database with status `pending` → AC-1
- [x] Post a duplicate `pull_request.opened` or `pull_request.synchronize` event while a review is active → returns `200 OK` with status `ignored` and reason `active_review_already_exists` → AC-1, AC-5
- [x] Post a pull request authored by `agentsonair[bot]` → returns `200 OK` with status `ignored` and reason `bot_author_excluded` → AC-1
- [x] Post an `issue_comment.created` webhook containing `@agentsonair review` on a pull request → fetches PR coordinates and queues review → AC-1
- [x] Trigger manual review via `POST /api/v1/repos/{repo_id}/pulls/{pr_number}/reviews` → review initiates, runs pipeline, and returns review ID → AC-5
- [x] Inspect review results via `GET /api/v1/reviews/{review_id}` → returns review summary, verdict, and list of structured findings → AC-5

## Commands
- [x] `uv run pytest tests/test_pr_code_reviewer.py -v` → 12/12 tests passing verifying symbol indexing, context budget allocator, verdict resolution, webhook bot exclusion, 422 line drift fallback, diff hunk parser boundaries, directory glob pruning, repository concurrency, and review REST endpoints → AC-1, AC-2, AC-3, AC-4, AC-5
- [x] `uv run pytest -v` → 67/67 tests passing across entire agent test suite → AC-1..AC-5
- [x] `pnpm typecheck && pnpm lint` → zero errors across web and agent packages → AC-1..AC-5
- [x] `uv run alembic current` → shows migration `e2a94519f802 (head)` applied → AC-1, AC-5

## Acceptance-criteria coverage
- AC-1: Review ingestion for `pull_request` and `issue_comment` triggers, bot exclusion, and active PR index guards covered by `tests/test_pr_code_reviewer.py::test_github_webhook_pr_events_and_bot_exclusion`.
- AC-2: Tree-sitter and AST symbol extraction with callers, callees, and hierarchies covered by `tests/test_pr_code_reviewer.py::test_symbol_indexer_and_context_budget_allocator`.
- AC-3: Two tier context budget allocator bounded within 64k tokens covered by `tests/test_pr_code_reviewer.py::test_symbol_indexer_and_context_budget_allocator`.
- AC-4: Structured reviewer node schema with deterministic verdict resolution (`changes_requested`, `comment`, `approved`) covered by `tests/test_pr_code_reviewer.py::test_reviewer_verdict_resolution_and_schema`.
- AC-5: Unified GitHub review publisher with `DiffHunkParser`, inline suggestion markdown, out of diff summary notes, and 422 diff drift fallback covered by `tests/test_pr_code_reviewer.py::test_review_publisher_with_line_placement_and_422_fallback` and `test_end_to_end_pr_review_use_case`.
