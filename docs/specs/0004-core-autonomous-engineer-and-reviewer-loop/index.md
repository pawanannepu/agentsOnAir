# 0004. Core autonomous engineer and reviewer loop

**Date**: 2026-11-22
**Status**: In Progress

## Summary

This decision establishes the core autonomous engineering and review loop for agentsOnAir. When an issue or webhook triggers a task, an isolated microVM sandbox initializes, Forge generates code and executes tests in an inner tool loop, an independent Reviewer validates the diff, Forge applies fixes in an outer bounded cycle, and the agent opens a verified GitHub pull request. This cyclical design ensures code is tested and reviewed before human submission, avoiding broken branches and noisy notifications.

## Requirements

**User stories**:
* As a software engineer, I want an autonomous agent to pick up GitHub issues and implement verified code changes in an isolated environment so that bug fixes and features arrive as ready to merge pull requests.
* As an engineering lead, I want every agent generated change reviewed by an independent critic node and validated with repository test suites before a pull request opens so that team standards and test suites never regress.
* As an organization administrator, I want task execution bounded by strict timeouts and iteration limits so that runaway agent loops never cause unexpected cloud costs or security leaks.

**Acceptance criteria**:
* **AC-1**: Task ingestion listens for `issues.opened`, `issues.labeled` (label `agentsonair`), and `issue_comment.created` (mention `@agentsonair`), scopes tasks to the repository tenant organization, prevents duplicate active runs via a partial unique index, and acknowledges ignored or duplicate webhooks with `200 OK`.
* **AC-2**: Cyclical LangGraph workflow orchestrates an inner ReAct loop where Forge edits files and runs tests iteratively, coupled with an outer review loop where Reviewer inspects diffs and bounds repair attempts to a maximum of 3 cycles.
* **AC-3**: Sandbox runner executes baseline tests on the base branch before Forge edits, runs repository test commands in the microVM without exposing GitHub write credentials, and streams command telemetry to Redis and checkpoint storage.
* **AC-4**: Reviewer evaluates the diff against issue requirements and test outputs, classifying findings as `critical`, `major`, `minor`, or `info`; any `critical` or `major` finding counts as blocking and triggers an outer repair cycle if under the 3 cycle cap.
* **AC-5**: When Reviewer approves with zero blocking findings and tests pass, host runner extracts the diff, commits as `agentsonair[bot]`, pushes the work branch, opens a pull request with changelog notes, and marks the task succeeded. If the cycle cap or timeout expires, the run halts as failed with diagnostic notes recorded in `task_runs.failure_reason` and immutable audit logs.

## Decision

**Chosen option**: Option 1: Cyclical two agent state graph with Forge inner tool loop, Reviewer critic, and bounded sandbox verification loop.

We adopt a cyclical two node LangGraph orchestration where Forge iterates internally using file and test tools inside an isolated sandbox, Reviewer evaluates the resulting diff with structured severities, and the outer loop cycles repair passes up to 3 times before opening a verified GitHub pull request.

**Implementation skills**: `fastapi-templates` (`wshobson/agents`, `.agents/skills/fastapi-templates/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

### Data model sketch

Enhancements to existing schema in PostgreSQL (from spec 0002):

#### Table: `tasks` (column additions and partial unique index)
* `base_branch`: VARCHAR(100) (Not Null, Default `main`)
* `pr_url`: VARCHAR(512) (Nullable, full web URL to created pull request)
* `head_commit_sha`: VARCHAR(40) (Nullable, commit SHA pushed to work branch)
* `pr_review_status`: VARCHAR(50) (Nullable, values: `pending`, `changes_requested`, `approved`)
* Partial unique index: `CREATE UNIQUE INDEX uq_tasks_active_repo_issue ON tasks (repo_id, (trigger_metadata->>'issue_number')) WHERE status IN ('queued', 'in_progress') AND deleted_at IS NULL`

#### Table: `review_iterations` (new table)
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE RESTRICT)
* `task_run_id`: UUID (Not Null, Foreign Key -> `task_runs.id` ON DELETE CASCADE)
* `cycle_number`: INTEGER (Not Null, 1 to 3)
* `verdict`: VARCHAR(50) (Not Null, values: `approved`, `changes_requested`)
* `summary`: TEXT (Not Null, narrative explanation of review decision)
* `findings`: JSONB (Not Null, Default `[]`) (array of objects: `file_path`, `line_number`, `severity` (values: `critical`, `major`, `minor`, `info`), `message`, `suggested_fix`)
* `blocking_count`: INTEGER (Not Null, Default 0) (count of critical and major findings)
* `non_blocking_count`: INTEGER (Not Null, Default 0) (count of minor and info findings)
* `diff_snapshot`: TEXT (Nullable, unified diff reviewed in this cycle)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Indexes: `(task_run_id, cycle_number)`, `(org_id, created_at DESC)`

### State transitions

Task execution lifecycle state machine:
* `queued`: Task created via webhook or console API, awaiting worker pick up.
* `in_progress`: Worker allocated sandbox, cloned repository, and initialized LangGraph.
  * Sub state `allocating_sandbox`: E2B microVM or Docker container provisioning.
  * Sub state `workspace_init`: Ephemeral token read only clone and branch checkout.
  * Sub state `baseline_testing`: Running test suite on untouched base branch. If failed, abort early as failed with `baseline_tests_failed`.
  * Sub state `forge_react_loop`: Claude 3.7 Sonnet iteratively reading files, applying edits, and executing local tests inside sandbox microVM until tests pass or inner step cap reached.
  * Sub state `reviewer_evaluating`: Claude 3.5 Sonnet / GPT 4o analyzing diff and test outputs, producing categorized findings.
  * Conditional transition:
    * If blocking findings exist (`blocking_count > 0`) AND cycle count < 3: increment cycle count and return to `forge_react_loop` with reviewer findings payload.
    * If blocking findings exist AND cycle count >= 3: transition to `failed` with reason `review_cycle_limit_exhausted`.
    * If zero blocking findings AND sandbox tests pass: proceed to host patch extraction.
  * Sub state `host_commit_push`: Host runner extracts diff from sandbox, verifies patch safety, commits as `agentsonair[bot]`, and pushes to GitHub with write token.
* `completed`: Pull request opened on GitHub, branch metadata updated, and audit log recorded.
* `failed`: Execution timed out, baseline failed, or maximum review cycles reached without approval.
* `cancelled`: User initiated abort via web console or API.

### API surface

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| /api/v1/webhooks/github | POST | GitHub event headers, payload (issue, comment, installation) | task_id (if queued), status: queued or ignored, reason (if ignored) | HMAC SHA256 webhook signature | 401 invalid signature, 400 invalid payload |
| /api/v1/tasks | POST | repo_id (UUID), title (str), description (str), base_branch (str, optional) | task object with id, status: queued | Clerk Bearer token (JWT) | 401 unauthorized, 404 repo not found, 422 invalid payload |
| /api/v1/tasks/{task_id} | GET | task_id (UUID path) | task details, latest run, review iterations list | Clerk Bearer token (JWT) | 401 unauthorized, 403 forbidden (org mismatch), 404 not found |

### Value sourcing

| Action | Value produced / displayed | Source |
|---|---|---|
| Ingest webhook | event_matched | Verified against event type `issues.opened`, `issues.labeled` (label `agentsonair`), or `issue_comment.created` (mention `@agentsonair`) |
| Ingest webhook | repo_id and org_id | Resolved by looking up `repositories` where `github_repo_id = payload.repository.id` |
| Ingest webhook | branch_name | Formatted as `agentsonair/task-{task_id_short}-issue-{issue_number}` using generated task UUID and issue number |
| Ingest webhook | base_branch | Sourced from `repositories.default_branch` or webhook repository payload |
| Allocate sandbox | sandbox_provider | Sourced from organization settings or environment default (`e2b` in cloud, `docker` in local development) |
| Workspace clone | git_read_token | Derived by requesting short lived installation token from GitHub App API scoped strictly to read only access |
| Sandbox baseline | baseline_test_status | Captured from exit code of initial test command execution on base branch |
| Forge tool loop | tool_telemetry | Stdout, stderr, and exit codes streamed to Redis pub sub channel `task:{id}:stream` and saved to `task_runs.checkpoint_state` |
| Review evaluation | verdict, findings, blocking_count | Computed by Reviewer node analyzing git diff and test output, counting critical and major severities |
| Host commit and push | head_commit_sha | Produced by host runner applying extracted sandbox diff, committing as `agentsonair[bot] <bot@agentsonair.dev>`, and pushing via host write token |
| Open pull request | pr_title | Formatted as `fix: {issue_title} (#{issue_number})` from task title and issue number |
| Open pull request | pr_body | Generated markdown summary containing issue link, changelog of changes, test outputs, and review cycle verdicts |
| Record failure | failure_reason | Written to `task_runs.failure_reason` and `audit_logs.payload_after` |

### Key invariants

* A pull request is never opened without zero blocking reviewer findings and passing sandbox tests.
* The outer review loop never exceeds 3 cycles per task run to prevent unbounded token expenditure.
* Repository write tokens are never injected into the sandbox environment; host runner extracts diff and executes git push.
* Sandbox microVM sessions have a strict hard timeout of 10 minutes total runtime and 120 seconds per shell command.
* If baseline tests on the base branch fail before Forge edits, the task terminates immediately without burning modification cycles.
* Work branches always use the prefix `agentsonair/` to avoid colliding with developer branches.

### Security model

* GitHub webhook requests require valid `X-Hub-Signature-256` matching the configured GitHub App webhook secret.
* Non matching webhook payloads return `200 OK` with status `ignored` rather than errors, avoiding webhook delivery retry storms.
* Console API requests require a valid Clerk JWT whose organization identifier matches the organization owning the target repository.
* The execution sandbox is isolated with read only workspace access. Write credentials exist solely on the host worker during the push phase.
* Sandboxes run untrusted code with no access to internal metadata services, host networks, or database credentials.

### Configuration required

* `GITHUB_APP_ID`: Application ID for GitHub App integration.
* `GITHUB_APP_PRIVATE_KEY`: PEM encoded RSA private key for generating GitHub App installation tokens.
* `GITHUB_WEBHOOK_SECRET`: HMAC SHA256 secret for validating webhook delivery signatures.
* `E2B_API_KEY`: API authentication key for creating E2B hardware microVM sandboxes.
* `ANTHROPIC_API_KEY`: Model provider key for Claude 3.7 Sonnet (Forge) and Claude 3.5 Sonnet (Reviewer).
* `OPENAI_API_KEY`: Optional fallback model provider key for GPT 4o review passes.

### Critical test scenarios

* Happy path: Webhook triggers task, baseline tests pass, Forge edits repository in inner loop, Reviewer approves on cycle 1, host pushes branch, and pull request opens on GitHub (verifies AC-1, AC-2, AC-3, AC-4, AC-5).
* Loop iteration and fix: Reviewer identifies critical syntax error or missing test on cycle 1, routes back to Forge, Forge applies fix on cycle 2, Reviewer approves, and pull request opens (verifies AC-2, AC-4, AC-5).
* Broken baseline abort: Base branch has broken tests upon clone, baseline runner detects failure, task halts immediately with `baseline_tests_failed`, and no cycles are wasted (verifies AC-3).
* Cycle limit exhaustion: Reviewer finds blocking security flaw across all 3 cycles, loop terminates, task marks failed with `review_cycle_limit_exhausted`, and no pull request is opened (verifies AC-2, AC-4, AC-5).
* Command timeout: Runaway test script exceeds 120 seconds in sandbox, command terminates, task run marks failed, and error logs upload to storage (verifies AC-3).
* Webhook authentication and duplicate rejection: Webhook with invalid HMAC returns 401; duplicate webhook for existing active issue returns 200 with `status: ignored` (verifies AC-1).

## Build plan

1. [x] Database migration for review iterations table, task pull request columns, and active task partial unique index, satisfies **AC-1**
2. [x] GitHub App webhook signature verification, event router, and duplicate check with 200 OK ignored handling, satisfies **AC-1**
3. [x] Sandbox workspace initializer, baseline test runner, and inner ReAct tool executor for E2B and Docker, satisfies **AC-3**
4. [x] LangGraph state machine with cyclical Forge coder and Reviewer critic nodes with structured severity scoring, satisfies **AC-2**, **AC-4**
5. [x] Host patch extraction, credential isolated branch push, pull request creation, and run audit log recording, satisfies **AC-5**

## Consequences

**Positive**:
* Proven end to end tracer bullet connects issue triggers to real pull requests through every layer.
* Inner ReAct loop lets Forge debug and test locally without exhausting outer review cycles on minor syntax issues.
* Credential isolation keeps repository write tokens on the host, preventing untrusted code from stealing push privileges.
* Baseline testing prevents agent from chasing pre existing bugs on the base branch.
* Strict iteration caps and execution timeouts protect against runaway token and cloud costs.

**Negative / tradeoffs**:
* Running multiple LLM passes (Forge coding plus Reviewer critique) increases token consumption per task compared to a single prompt agent.
* Running baseline tests plus Forge test runs adds extra sandbox runtime latency before a pull request appears.

**Neutral**:
* Local testing relies on Docker containers while cloud environments utilize E2B hardware microVMs.
* Initial review criteria focus on diff correctness and test results; custom team guidelines arrive in later slices.

## Follow-up

* [ ] Add unit test suite for GitHub webhook signature validation and payload parsing.
* [ ] Implement Docker sandbox container definition matching E2B base runtime environment.
* [ ] Wire Redis pub sub streaming from LangGraph step callbacks to web console SSE endpoints.
