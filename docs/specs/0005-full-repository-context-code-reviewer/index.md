# 0005. Full repository context code reviewer

**Date**: 2026-11-24
**Status**: In Progress

## Summary

This decision establishes a full repository context code reviewer for pull requests. When a pull request opens, synchronizes, or receives an explicit review mention, the system inspects the change, extracts repository symbols with tree-sitter, gathers callers, callees, and project conventions beyond the diff, and ranks findings by severity using Claude Sonnet. Findings publish back to GitHub as a single review with inline diff suggestions and summary notes for cross file concerns. This gives engineering teams deep automated code review without runaway token costs, duplicate review races, or infinite bot feedback loops.

## Requirements

**User stories**:
* As a software engineer submitting a pull request, I want an automated review that checks the whole repository context so that subtle regressions, type mismatches, and architectural breaks are caught before my teammates spend time reviewing.
* As an engineering lead, I want review findings categorized by severity with inline diff suggestions so that critical flaws block approval while small style suggestions can be applied in one click.
* As a platform administrator, I want automated reviews bounded by strict token budgets and bot author exclusions so that costs remain predictable and bots never get stuck in infinite review loops.

**Acceptance criteria**:
* **AC-1**: Review ingestion listens for GitHub `pull_request.opened`, `pull_request.synchronize`, and `issue_comment.created` (containing `@agentsonair review` on a pull request), fetches commit details from GitHub API for comment triggers, disambiguates from autonomous engineer issue tasks, filters out pull requests authored by `agentsonair[bot]` (and comments from bot senders), and acknowledges events with `200 OK`.
* **AC-2**: Symbol indexing extracts language symbols, function signatures, caller and callee hierarchies, and project architectural rules using tree-sitter across Python, TypeScript, and supported languages, extracting files from a shallow tarball in a temporary directory, caching symbol graph snapshots in ephemeral worker memory and Redis metadata keyed by commit SHA.
* **AC-3**: Two tier context budget allocator packs the modified diff hunks and prioritized symbol context within a strict 64k token budget: Tier 1 (diff hunks plus root `AGENTS.md`, up to 32k tokens), Tier 2 (direct callers, callees, enclosing class or module types, up to 28k tokens), and a 4k token reserve for model completion.
* **AC-4**: Review engine prompts Claude 3.5 Sonnet or Claude 3.7 Sonnet using a structured tool schema, classifying findings into `critical`, `major`, `minor`, and `info` severities across `security`, `bug`, `performance`, `architecture`, and `style` categories; deterministically resolving the review verdict to `changes_requested` if blocking findings exist, `comment` if only non blocking findings exist, and `approved` if zero findings exist and `allow_approval` is enabled in repository settings.
* **AC-5**: GitHub review submission posts a unified review with a markdown summary verdict, attaches inline diff comments with markdown suggestion blocks for lines verified within diff hunks by `DiffHunkParser`, formats out of diff architectural findings as permalink references in the summary narrative, falls back to summary only if GitHub returns 422 line drift errors, and stores records in `pull_request_reviews` and `pr_review_findings` with an active PR partial unique index guarding against concurrency races.

## Decision

**Chosen option**: Option 1: Hybrid symbol graph context expansion with tree-sitter parsing and unified GitHub review submissions.

We adopt an event driven code review pipeline that indexes repository symbols with tree-sitter, packs relevant callers and callees into a bounded two tier 64k token prompt window, and submits a single unified review with inline diff comments, out of diff summary notes, and automatic 422 line drift fallback.

**Implementation skills**: `fastapi-templates` (`wshobson/agents`, `.agents/skills/fastapi-templates/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

### Data model sketch

Enhancements to existing PostgreSQL schema:

#### Table: `pull_request_reviews`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE CASCADE)
* `repo_id`: UUID (Not Null, Foreign Key -> `repositories.id` ON DELETE CASCADE)
* `task_id`: UUID (Nullable, Foreign Key -> `tasks.id` ON DELETE SET NULL, populated only if spawned by an internal autonomous loop task, NULL for webhook triggered reviews)
* `pr_number`: INTEGER (Not Null)
* `pr_title`: VARCHAR(512) (Not Null)
* `pr_author`: VARCHAR(100) (Not Null)
* `head_commit_sha`: VARCHAR(40) (Not Null)
* `base_commit_sha`: VARCHAR(40) (Not Null)
* `status`: VARCHAR(50) (Not Null, values: `pending`, `analyzing`, `reviewing`, `posting`, `completed`, `failed`)
* `verdict`: VARCHAR(50) (Nullable, values: `approved`, `changes_requested`, `comment`)
* `summary`: TEXT (Nullable, overall review narrative written in markdown)
* `github_review_id`: BIGINT (Nullable, GitHub review submission ID)
* `context_token_count`: INTEGER (Not Null, Default 0)
* `model_name`: VARCHAR(100) (Not Null)
* `execution_duration_ms`: INTEGER (Nullable)
* `error_message`: TEXT (Nullable)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Indexes:
  * `(repo_id, pr_number, created_at DESC)`
  * `(org_id, created_at DESC)`
  * Partial unique index for active reviews: `CREATE UNIQUE INDEX uq_pr_reviews_active_pr ON pull_request_reviews (repo_id, pr_number) WHERE status IN ('pending', 'analyzing', 'reviewing', 'posting');`

#### Table: `pr_review_findings`
* `id`: UUID (v7, Primary Key)
* `review_id`: UUID (Not Null, Foreign Key -> `pull_request_reviews.id` ON DELETE CASCADE)
* `file_path`: VARCHAR(1024) (Not Null)
* `start_line`: INTEGER (Nullable, for multi line comments)
* `line_number`: INTEGER (Not Null)
* `side`: VARCHAR(10) (Not Null, Default `RIGHT`, values: `LEFT`, `RIGHT`)
* `severity`: VARCHAR(20) (Not Null, values: `critical`, `major`, `minor`, `info`)
* `category`: VARCHAR(50) (Not Null, values: `security`, `bug`, `performance`, `architecture`, `style`)
* `title`: VARCHAR(255) (Not Null)
* `message`: TEXT (Not Null)
* `suggested_patch`: TEXT (Nullable, markdown diff suggestion block)
* `github_comment_id`: BIGINT (Nullable, GitHub inline comment ID)
* `status`: VARCHAR(30) (Not Null, Default `open`, values: `open`, `resolved`, `outdated`, `dismissed`)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Indexes: `(review_id, severity)`, `(review_id, file_path)`

#### Table: `repositories` (extension)
* `review_settings`: JSONB (Not Null, Default `'{"enabled": true, "auto_review": true, "allow_approval": false, "ignore_all_bots": false, "min_severity": "info", "max_comments": 25, "ignored_paths": ["*.lock", "dist/**", "node_modules/**"]}'::jsonb`)

### Structured tool schema for reviewer node

Claude Sonnet outputs findings through this structured schema:

```json
{
  "summary": "string (narrative markdown overview of review findings and architectural observations)",
  "findings": [
    {
      "file_path": "string",
      "line_number": "integer",
      "start_line": "integer | null",
      "side": "RIGHT | LEFT",
      "severity": "critical | major | minor | info",
      "category": "security | bug | performance | architecture | style",
      "title": "string",
      "message": "string",
      "suggested_patch": "string | null"
    }
  ]
}
```

### Context budget tiers

The 64k token context window is partitioned deterministically:
* **Tier 1 (Mandatory Core, up to 32k tokens)**: System instructions plus root `AGENTS.md` (capped at 4k tokens) plus unified git diff hunks with 5 context lines.
* **Tier 2 (Symbol Graph Expansion, up to 28k tokens)**: Direct callers, callees, and enclosing class or module types parsed via tree-sitter.
* **Reserve Buffer (4k tokens)**: Reserved for model reasoning, completion, and tool response payload.
* **Pruning sequence**: If content exceeds limits, prune in this order: (1) ignored and lock files, (2) callees, (3) callers, (4) truncate largest diff hunks and record an omitted file notice in the review summary.
* **Tokenizer**: `tiktoken` with `cl100k_base` encoding for local counting without external API calls.

### State transitions

Review execution lifecycle:
* `pending`: Webhook ingested or manual review triggered, active review index verified, job placed on worker queue.
* `analyzing`: Worker allocated, shallow repository tarball downloaded to temporary directory, tree-sitter symbol graph generated, diff hunks extracted.
* `reviewing`: Context budget assembled (Tier 1 diff plus Tier 2 symbol call graph), Claude Sonnet invoked with structured finding tools.
* `posting`: Review payload validated by `DiffHunkParser`, inline comments positioned within diff hunks, out of diff findings formatted as permalinks in summary, GitHub review API submitted (with automatic 422 line drift fallback to summary text if rejected).
* `completed`: Review published to GitHub, database records persisted, audit log emitted.
* `failed`: Execution failed due to timeout, rate limits, or parse error, error details recorded in `error_message`.

### API surface

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| /api/v1/webhooks/github | POST | GitHub event headers, payload (pull request, comment) | status: queued or ignored, review_id (if queued) | HMAC SHA256 webhook signature | 401 invalid signature, 400 invalid payload |
| /api/v1/repos/{repo_id}/pulls/{pr_number}/reviews | POST | repo_id (UUID path), pr_number (int path) | review object with id, status: pending | Clerk Bearer token (JWT) | 401 unauthorized, 404 repo not found, 409 review already running |
| /api/v1/repos/{repo_id}/pulls/{pr_number}/reviews | GET | repo_id (UUID path), pr_number (int path) | list of review summary items | Clerk Bearer token (JWT) | 401 unauthorized, 404 repo not found |
| /api/v1/reviews/{review_id} | GET | review_id (UUID path) | review details, summary, list of findings | Clerk Bearer token (JWT) | 401 unauthorized, 403 forbidden (org mismatch), 404 not found |

### Value sourcing

| Action | Value produced / displayed | Source |
|---|---|---|
| Ingest pull request webhook | event_matched | Verified against `pull_request.opened` or `pull_request.synchronize` |
| Ingest comment webhook | event_matched | Verified against `issue_comment.created` where comment body contains `@agentsonair review` and `payload.issue.pull_request` is present |
| Ingest comment webhook | pr_number and PR metadata | Sourced by calling GitHub API `GET /repos/{owner}/{repo}/pulls/{issue_number}` using installation token |
| Ingest webhook | repo_id and org_id | Resolved by looking up `repositories` where `github_repo_id = payload.repository.id` |
| Ingest webhook | pr_author | Extracted from `payload.pull_request.user.login` or fetched PR object |
| Ingest webhook | head_commit_sha and base_commit_sha | Extracted from `payload.pull_request.head.sha` and `base.sha`, or fetched PR object |
| Authorize review | bot_exclusion_verdict | Computed by checking if `pr_author == "agentsonair[bot]"` (or any bot if `ignore_all_bots` is enabled), and confirming comment sender is not a bot |
| Disambiguate routing | target_pipeline | If comment contains `@agentsonair review` on PR: route to PR reviewer; if comment contains `@agentsonair` on regular issue: route to Spec 0004 autonomous engineer; if `@agentsonair review` on regular issue: ignore with note |
| Fetch repository context | git_installation_token | Minted on demand from GitHub App private key for repository installation |
| Fetch repository context | raw_diff | Retrieved from GitHub API using header `Accept: application/vnd.github.v3.diff` |
| Extract symbols | symbol_call_graph | Parsed via tree-sitter against code files extracted from shallow tarball `GET /repos/{owner}/{repo}/tarball/{head_commit_sha}` |
| Assemble context | context_token_count | Counted via `tiktoken` (`cl100k_base`), budgeted into Tier 1 (32k), Tier 2 (28k), and Reserve (4k) |
| Run review | verdict | Resolved deterministically: `changes_requested` if blocking findings exist, `comment` if only non blocking findings exist, `approved` if zero findings exist and `allow_approval` is enabled |
| Run review | findings | Generated by Claude Sonnet tool call with structured review schema |
| Validate line placement | is_in_diff_hunk | Computed by `DiffHunkParser` matching finding file, line, and side against diff hunk ranges |
| Publish review | github_review_id | Returned by GitHub API `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` |
| Publish review fallback | fallback_applied | If GitHub returns 422 on line placement, reformat inline findings into markdown summary and submit review with empty inline list |

### Key invariants

* Pull requests authored by `agentsonair[bot]` are never automatically reviewed, preventing recursive review cycles.
* When a pull request review is already active in status `pending`, `analyzing`, `reviewing`, or `posting`, subsequent triggers for that same pull request are rejected or queued cleanly via the partial unique index `uq_pr_reviews_active_pr`.
* The total context prompt sent to the model never exceeds 64,000 tokens, enforced by the two tier budget allocator.
* Inline comments are submitted only for line numbers that exist within the pull request diff hunks; out of diff findings are placed in the review summary text as GitHub permalinks.
* If a GitHub batch review submission fails with HTTP 422 due to diff drift, the publisher catches the error and resubmits all findings within the top level review summary narrative.
* Every review and finding record is strictly scoped to an organization (`org_id`) and repository (`repo_id`).
* When blocking findings exist (`critical` or `major`), the verdict defaults to `changes_requested`; when only non blocking findings exist, the verdict is `comment`; verdict is `approved` only when zero findings exist and `allow_approval` is explicitly enabled.

### Security model

* Tenant organization scoping: All queries and mutations require `org_id` match.
* Ephemeral GitHub tokens: Access tokens are generated with minimum required permissions (contents read, pull requests write) and expired immediately.
* Secret filtering: File contents are scanned for standard credential patterns (keys, tokens, certificates) and redacted before model prompt assembly.
* Audit logging: Every review initiation, completion, and failure emits an immutable audit event.

### Configuration required

* `GITHUB_APP_ID`: GitHub App identification number
* `GITHUB_APP_PRIVATE_KEY`: Private key pem string for generating installation tokens
* `GITHUB_WEBHOOK_SECRET`: HMAC SHA256 secret for validating webhook signatures
* `ANTHROPIC_API_KEY`: API credential for Claude Sonnet model inference

### Critical test scenarios

* Happy path: Ingest `pull_request.opened`, parse symbol call graph from shallow tarball, assemble context within 64k tokens, generate findings, and post review with inline diff comments, verifies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**
* Comment trigger PR detail resolution: Ingest `issue_comment.created` mentioning `@agentsonair review` on a pull request, resolve `head_commit_sha` via GitHub API, and trigger review run, verifies **AC-1**
* Routing disambiguation: Ingest comment mentioning `@agentsonair` without `review` on regular issue, verify it routes to Spec 0004 task and does not trigger PR reviewer, verifies **AC-1**
* Bot author exclusion: Ingest pull request authored by `agentsonair[bot]`, acknowledge webhook with `200 OK`, verify no review task is queued, verifies **AC-1**
* Concurrency guard on rapid synchronize: Ingest two `pull_request.synchronize` events simultaneously, verify only one review enters active state and duplicate is rejected via partial unique index, verifies **AC-5**
* Two tier context budget pruning: Ingest pull request with large lock files and 2,000 modified lines, verify generated files are skipped, Tier 1 and Tier 2 fit within 64k token budget, and summary notes omitted files, verifies **AC-3**, **AC-4**
* Out of diff comment routing: Finding pointing to unchanged function caller outside diff hunk is formatted in summary narrative with line permalink rather than failing GitHub review API, verifies **AC-5**
* Line drift 422 fallback: Simulate GitHub API returning 422 on invalid diff line, verify publisher falls back to summary only submission with zero loss of findings, verifies **AC-5**
* Rate limit backoff: GitHub API returns 403 secondary rate limit, worker applies exponential backoff with jitter and successfully delivers review on retry, verifies **AC-5**

## Build plan

1. [x] Database migration: Create `pull_request_reviews` and `pr_review_findings` tables with active PR partial unique index and add `review_settings` JSONB column to `repositories`, satisfies **AC-1**, **AC-5**
2. [x] Webhook ingestion router: Extend GitHub webhook handler for `pull_request` and `issue_comment` review triggers with PR detail resolution, bot author filtering, and disambiguation from issue tasks, satisfies **AC-1**
3. [x] Tree-sitter symbol indexer: Build multi language symbol parser extracting function definitions, call hierarchies, and enclosing types from shallow repository tarballs, satisfies **AC-2**
4. [x] Two tier context budget allocator: Implement diff hunk parser, file pruner, and call graph context assembler bounded to Tier 1 (32k), Tier 2 (28k), and Reserve (4k), satisfies **AC-3**
5. [x] Structured review analyzer node: Create Pydantic finding tool schema and LangGraph reviewer node utilizing Claude Sonnet with deterministic verdict resolution, satisfies **AC-4**
6. [x] GitHub review publisher: Build review submission service with `DiffHunkParser`, inline suggestion markdown builder, out of diff permalink renderer, and automatic 422 line drift fallback, satisfies **AC-5**
7. [x] Console review API endpoints: Expose REST endpoints for manual review triggers, review history, and finding details, satisfies **AC-5**

## Consequences

**Positive**:
* Captures cross file regressions and interface mismatches that diff only tools miss.
* Inline comments with suggested diff patches allow developers to accept fixes immediately.
* Predictable token usage and cost bounds through the two tier 64k token context allocator.
* Eliminates accidental bot on bot review loops and concurrent review race conditions.
* Robust fallback prevents lost reviews when lines drift between analysis and posting.

**Negative / tradeoffs**:
* Tree-sitter grammars require native compiled dependencies in the worker container image.
* Initial symbol parsing adds 5 to 15 seconds of execution latency prior to model analysis.

**Neutral**:
* Cross file architectural findings that point to code outside the PR diff appear in the summary markdown rather than as inline diff comments due to GitHub API constraints.

## Follow-up

* [ ] Connect live review progress streaming to the web console in Slice 3 (spec 0007)
* [ ] Implement team custom review guidelines and dismiss feedback learning in Slice 5 (spec 0009)
