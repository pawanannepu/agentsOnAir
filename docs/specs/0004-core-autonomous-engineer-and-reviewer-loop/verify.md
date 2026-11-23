# Verify: core autonomous engineer and reviewer loop · spec 0004 · updated 2026-11-23

_Steps derived from spec 0004 acceptance criteria. `/check verify` runs these, and `/test` locks the durable ones._

## Commands

- [x] `pnpm --filter agent test tests/test_webhooks.py` → all webhook delivery, signature verification, and duplicate check tests pass → AC-1
- [x] `pnpm --filter agent test tests/test_autonomous_loop.py` → all five loop scenarios pass including happy path, cycle repair, baseline abort, cycle exhaustion, and sandbox timeout → AC-2, AC-3, AC-4, AC-5
- [x] `pnpm --filter agent test tests/test_review_iterations.py` → review iteration persistence and partial unique active task index tests pass → AC-1, AC-4
- [x] `pnpm --filter agent test tests/test_migration.py` → alembic upgrade and downgrade migration cycle executes cleanly → AC-1
- [x] `pnpm --filter agent typecheck && pnpm --filter agent lint` → zero type errors and zero ruff lint warnings → AC-1, AC-2, AC-3, AC-4, AC-5
- [x] `pnpm typecheck && pnpm lint && pnpm test` → whole monorepo typecheck, lint, and test suites pass green across web and agent workspaces → AC-1, AC-2, AC-3, AC-4, AC-5

## Value sourcing verification

- [x] Webhook ingest event matching: send `issues.opened`, `issues.labeled` (`agentsonair`), and `issue_comment.created` (`@agentsonair`) → all three produce queued tasks while other events return 200 OK ignored
- [x] Webhook repository resolution: verify `repo_id` and `org_id` resolve from database repository table matching `github_repo_id`
- [x] Branch naming derivation: verify work branch matches `agentsonair/task-{task_id_short}-issue-{issue_number}`
- [x] Base branch resolution: verify base branch resolves from repository default branch, defaulting to `main`
- [x] Sandbox allocation: verify sandbox provider allocates isolated workspace session and logs run record
- [x] Baseline test exit code: verify non zero baseline exit code aborts task immediately with `baseline_tests_failed`
- [x] Telemetry streaming: verify stdout, stderr, and exit codes publish to channel `task:{id}:stream` and save to task run checkpoint state
- [x] Review evaluation: verify Reviewer classifies findings into critical, major, minor, or info and accurately counts blocking issues
- [x] Host commit identity: verify host commits as `agentsonair[bot] <bot@agentsonair.dev>` and produces 40 character SHA
- [x] Pull request metadata: verify pull request title matches `fix: {issue_title} (#{issue_number})` with markdown changelog body
- [x] Failure diagnostics: verify failure reasons write to `task_runs.failure_reason` and immutable audit logs

## Acceptance criteria coverage

- AC-1 (Webhook ingestion, filtering, duplicate index, 200 OK ignored) · covered by webhook tests and migration tests
- AC-2 (Cyclical LangGraph loop with Forge coder and Reviewer critic up to 3 cycles) · covered by autonomous loop scenario 1, scenario 2, and scenario 4
- AC-3 (Sandbox runner baseline tests, read only isolation, and telemetry) · covered by autonomous loop scenario 1, scenario 3, and scenario 5
- AC-4 (Reviewer structured severity classification and blocking count routing) · covered by review iterations tests and autonomous loop scenario 1, scenario 2, scenario 4
- AC-5 (Host patch extraction, credential isolated push, pull request creation, audit logging) · covered by autonomous loop scenario 1, scenario 2, and scenario 4
