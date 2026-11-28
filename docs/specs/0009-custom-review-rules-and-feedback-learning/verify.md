# Verify: custom review rules & feedback learning · spec 0009 · updated 2026-11-28
_Steps derived from spec 0009 acceptance criteria and value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [x] Sign in as `org:admin`, open `/settings`, create an organization default rule with `path_globs: ["**/*"]`, toggle it, and soft delete a rule → expect persisted state and `audit_logs` records (`review_rule.*`) → AC-1, AC-7
- [x] Open `/repositories`, open a repository drawer, and switch across all four tabs (`Guardrails`, `Rules & Overrides`, `Example PRs`, `Learned Preferences`); override an org rule severity and clear both `is_enabled` and `severity_override` to `null` → expect override row removed and effective rule reset → AC-1, AC-7
- [x] Sign in as a non admin `org:member`, open `/repositories` drawer → expect read only controls with mutations disabled and `403` if calling rule, example, or preference write endpoints → AC-1, AC-2, AC-4, AC-7
- [x] In `Example PRs`, attach a valid same repo PR URL and a foreign repo PR URL → expect `201` with cached `modified_files` and `[REDACTED]` secret scrubbing on same repo, and `422` on cross repo mismatch or 6th example → AC-2, AC-7
- [x] Open `/reviews`, filter by repository, open a review detail, click `Accept` and `Dismiss` (with optional `reason` and `remember_preference` checked) → expect finding `feedback_state` updates and learned preference status transitions (`active` → `dampened` → `suppressed`) → AC-3, AC-4, AC-7
- [x] Open `/analytics`, switch timeframe (`7d`, `30d`, `90d`) and repository filter → expect KPI cards, custom SVG daily spend and turnaround charts, severity/category breakdowns, top rules table, and zero states → AC-6, AC-7

## Commands
- [x] `cd apps/agent && uv run pytest tests/test_custom_review_rules.py -v` → expects all 6 tests passing (globstar root matching, 25 rule cap, example PR GitHub HTTP fetch & redaction, comment ID backfill, webhook `author_association` and `github_event_id` guards, Tier 1 pruning, XML escaping, SQL analytics percentiles and UTC cost split) → AC-1, AC-2, AC-3, AC-4, AC-5, AC-6
- [x] `cd apps/agent && uv run pytest tests/test_migration.py tests/test_health.py tests/test_pr_code_reviewer.py tests/test_autonomous_loop.py -q` → expects clean Alembic `upgrade` / `downgrade` cycle and zero regressions across core review and autonomous loop pipelines → AC-1, AC-5
- [x] `cd apps/agent && uv run ruff check . && uv run pyright` → expects 0 lint errors and 0 type errors → AC-1, AC-5
- [x] `pnpm --filter web typecheck && pnpm --filter web lint && pnpm --filter web test && pnpm --filter web build` → expects TypeScript, ESLint, Vitest (`77` tests across 10 files including Drizzle schema backfill), and Next.js production build passing → AC-7

## Value sourcing checks
- [x] Merge active repo rules: verify a rule with `path_globs: ["**/*"]` matches root file `README.md`, repo rules sort before org defaults at equal severity, and `GET /api/v1/repositories/{id}/review-rules` caps active merged rules at 25 → AC-1, AC-5
- [x] Match learned preferences: verify a bare dismissal (`remember_preference=false`, empty `reason`) at streak 1 is not injected, streak 2 becomes `dampened` and downgrades blocking severity to `info` advisory, streak 3 becomes `suppressed` and filters findings, and `accepted` resets streak to `0` → AC-4, AC-5
- [x] Select example PRs: verify `ContextBudgetAllocator` ranks example PRs by overlap count with PR modified files DESC then `updated_at` DESC and prunes examples, then preferences, then lowest priority rules before diff hunks within Tier 1 (`<= 32,000` tokens via `tiktoken`) → AC-2, AC-5
- [x] Link GitHub comments & parse webhooks: verify `GitHubReviewPublisher.publish` persists `pr_review_findings.github_comment_id`, `pull_request_review_thread` (`resolved`/`unresolved`) and `pull_request_review_comment` replies ignore `NONE` association or missing `X-GitHub-Delivery`, and duplicate `github_event_id` deliveries are deduplicated atomically → AC-3
- [x] Compute analytics overview: verify `GET /api/v1/analytics/overview` subtracts `paused_seconds` from task run duration, returns `null` acceptance rate when `accepted + dismissed == 0`, zero fills UTC daily buckets, splits `pr_review` vs `forge` + `reviewer` costs, and returns `404` for a foreign `repo_id` → AC-6

## Acceptance-criteria coverage
- AC-1 covered by org/repo rules, overrides, 25 cap, globstar matcher, and audit logs checks · AC-2 covered by example PR GitHub fetch, redaction, 1,500 token cache, and 5 cap checks · AC-3 covered by comment ID backfill, console feedback, and gated GitHub webhook checks · AC-4 covered by preference pattern keys, dampening/suppression, idempotency, and admin edit checks · AC-5 covered by `tiktoken` Tier 1 budgeting, XML escaping, `rule_id` validation, and `RunPRReviewUseCase` / `reviewer_node` integration checks · AC-6 covered by `/api/v1/analytics/overview` SQL percentiles, acceptance rate, and UTC daily series checks · AC-7 covered by Drizzle schema backfill, `/analytics`, `/reviews`, `/settings`, and `/repositories` drawer checks
