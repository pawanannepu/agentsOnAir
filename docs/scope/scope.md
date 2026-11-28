# Scope: agentsOnAir

An autonomous software engineering and code review platform that develops, tests, and verifies code in isolated sandboxes before opening verified pull requests.

**Build approach:** Tracer Bullet (prove the whole loop works end to end through every layer before broadening features).
**Workflow:** GA (after develop, run check verify, automated tests, a fresh reviewer check, and document). The project default level of rigor. `/architect` is the recommended first stop for a feature with a real decision, but skippable when you already know the build. Any feature can carry its own tag to do more or less.

_These are recommendations to keep your build orderly, not requirements. Skip anything that does not fit: if you already know how to build a feature, use `/develop` and skip `/architect`. You decide when a feature is `done`._

## At a glance

| # | Feature | Phase | Status |
|---|---------|-------|--------|
| 1 | Stack & architecture | Foundation | done |
| 2 | Coding standards & tooling | Foundation | in-progress |
| 3 | Data model | Foundation | in-progress |
| 4 | Design system & console UI foundation | Foundation | done |
| 10 | Clerk sign in & organization switcher | Foundation | in-progress |
| 5 | Core autonomous engineer and reviewer loop | Slice 1 | in-progress |
| 6 | Full repository context code reviewer | Slice 2 | in-progress |
| 7 | Live task streaming & interactive collaboration | Slice 3 | in-progress |
| 8 | Guardrails, branch protection & budget limits | Slice 4 | in-progress |
| 9 | Custom review rules & feedback learning | Slice 5 | in-progress |

## Foundations

### 1. Stack & architecture
Choose the primary runtime, language, and orchestrator framework, then scaffold a runnable repository so every later slice builds on real structure.
**Done when:** the stack is recorded in a spec, and the empty scaffold builds, passes tests, and runs locally.
spec [0001](../specs/0001-stack-and-architecture/index.md) · code in `apps/`
- [x] Decide the stack (spec): `/architect stack & architecture`
- [x] Scaffold from the decision: `/develop stack & architecture`
- [x] Verify it: `/check verify stack & architecture`
- [x] Test it: `/test stack & architecture`
- [x] Review it (fresh model): `/check review stack & architecture`
- [x] Document it: `/document stack & architecture`

### 2. Coding standards & tooling
Capture conventions, then install lint, format, typecheck, and test runner tooling from the real scaffolded project.
**Done when:** root `AGENTS.md` reflects conventions, and lint, format, typecheck, and test commands run clean.
- [x] Capture conventions and tooling choices: `/audit`
- [x] Install the tooling: `/develop tooling`
- [x] Check it runs clean: `/test`

### 3. Data model
Core database schema for tenant organizations, repositories, agent tasks, sandbox runs, audit logs, and encrypted credentials.
**Done when:** entities and migrations support task execution, tenant isolation, and audit events without breaking changes.
spec [0002](../specs/0002-data-model/index.md) · code in `apps/agent/app/infrastructure/db/`, `apps/web/src/db/`
- [x] Design it (spec): `/architect data model`
- [x] Build it: /develop data model
  - [x] UUIDv7 base models, AES 256 GCM security utility, and SQLAlchemy declarative models (AC-1, AC-5)
  - [x] Alembic migration with partial unique indexes and audit immutability trigger (AC-1, AC-6, AC-7, AC-8)
  - [x] Domain repository protocols and async SQLAlchemy repository implementations (AC-2, AC-3, AC-6, AC-7)
  - [x] Drizzle ORM read schemas in web console and integration test suite (AC-1, AC-2, AC-8)
- [x] Verify it: /check verify data model
- [x] Test it: /test data model
- [x] Review it (fresh model): /check review data model
- [x] Document it: /document data model

### 4. Design system & console UI foundation
Visual design tokens, layout primitives, and reusable UI components for the web console so developers can inspect tasks and configure settings.
**Done when:** design tokens define colors, typography, layout, and accessible base components support keyboard and screen navigation.
spec [0003](../specs/0003-design-system-and-console-ui/index.md) · code in `apps/web/src/`
- [x] Design it (spec): `/architect design system & console UI foundation`
- [x] Build it: /develop design system & console UI foundation
  - [x] Tailwind CSS v4 @theme design tokens, CSS first configuration, and utility helper (AC-1)
  - [x] Core accessible CVA component primitives (Button, Badge, Card, Dialog, Tabs, Table, Input, Select) (AC-2)
  - [x] Virtualized streaming TerminalViewer with ANSI parsing, auto scroll pin, and copy action (AC-3)
  - [x] Sonner toast integration and Cmd+K CommandDialog global palette (AC-4, AC-5)
  - [x] ConsoleLayout shell, collapsible Sidebar, Header with breadcrumbs, and route views (AC-6)
- [x] Verify it: /check verify design system & console UI foundation
- [x] Test it: /test design system & console UI foundation
- [x] Review it (fresh model): /check review design system & console UI foundation
- [x] Document it: /document design system & console UI foundation

### 10. Clerk sign in & organization switcher
Protect console routes with Clerk authentication, render dark themed sign in and organization switching UI, and synchronize Clerk organizations into PostgreSQL.
**Done when:** unauthenticated visitors redirect to sign in, signed in users select or create an organization, `org:admin` guards settings, and Clerk organization events plus lazy Backend API sync keep PostgreSQL `organizations` accurate.
spec [0007](../specs/0007-clerk-sign-in-and-organization-switcher/index.md) · code in `apps/agent/`, `apps/web/`
- [x] Design it (spec): `/architect clerk sign in & organization switcher`
- [x] Build it: `/develop clerk sign in & organization switcher`
  - [x] Core auth route groups, edge proxy, health route, and FastAPI Clerk config (AC-1, AC-2, AC-3)
  - [x] Svix webhook endpoint and atomic PostgreSQL organization upsert and soft delete (AC-5)
  - [x] Isolated lazy Clerk Backend API fallback sync, structured 403 errors, and org:admin guard (AC-4, AC-6)
  - [x] Protected console pages, sign in and onboarding UI, sidebar OrganizationSwitcher, and 403 recovery prompt (AC-1, AC-2, AC-3, AC-4, AC-7)
- [ ] Verify it: `/check verify clerk sign in & organization switcher`
- [ ] Test it: `/test clerk sign in & organization switcher`
- [ ] Review it (fresh model): `/check review clerk sign in & organization switcher`
- [ ] Document it: `/document clerk sign in & organization switcher`

## Slice 1: Core autonomous engineer and reviewer loop

### 5. Core autonomous engineer and reviewer loop
Connect the initial working thread through every layer: a GitHub task trigger starts an isolated sandbox, forge writes code and runs tests against a mock repository and mock model harness, the independent reviewer checks the diff, forge applies fixes, and opens a verified GitHub pull request.
**Done when:** an issue or webhook triggers a task, runs in an isolated sandbox, passes autonomous review, and opens a pull request with changelog and audit trail.
spec [0004](../specs/0004-core-autonomous-engineer-and-reviewer-loop/index.md) · code in `apps/agent/`
- [x] Design it (spec): `/architect core autonomous engineer and reviewer loop`
- [x] Build it: /develop core autonomous engineer and reviewer loop
  - [x] Database migration for review iterations, task PR fields, and active task index (AC-1)
  - [x] GitHub App webhook handler, event router, and duplicate filter (AC-1)
  - [x] Sandbox workspace init, baseline test runner, and inner ReAct tool runner (AC-3)
  - [x] Cyclical LangGraph engine with Forge coder and Reviewer critic (AC-2, AC-4)
  - [x] Host patch extraction, branch push, PR creation, and audit logging (AC-5)
- [x] Verify it: /check verify core autonomous engineer and reviewer loop
- [x] Test it: /test core autonomous engineer and reviewer loop
- [x] Review it (fresh model): /check review core autonomous engineer and reviewer loop
- [x] Document it: /document core autonomous engineer and reviewer loop

## Slice 2: Full repository context code reviewer

### 6. Full repository context code reviewer
Review pull requests authored by humans or agents by reading the full repository context, ranking issues by severity, and posting line comments and suggested fixes.
**Done when:** a pull request triggers a review that analyzes repository context beyond the diff, ranks findings by severity, and posts actionable comments to GitHub.
spec [0005](../specs/0005-full-repository-context-code-reviewer/index.md) · code in `apps/agent/`
- [x] Design it (spec): `/architect full repository context code reviewer`
- [x] Build it: /develop full repository context code reviewer
  - [x] Database migration for PR reviews, findings, active unique index, and review settings (AC-1, AC-5)
  - [x] GitHub webhook router extension with PR detail fetch and bot author exclusion (AC-1)
  - [x] Tree-sitter symbol indexer and two tier context budget allocator (AC-2, AC-3)
  - [x] LangGraph structured reviewer node with Claude Sonnet (AC-4)
  - [x] GitHub review publisher with DiffHunkParser, inline suggestions, and 422 fallback (AC-5)
  - [x] Console REST API endpoints for PR reviews and findings (AC-5)
- [x] Verify it: /check verify full repository context code reviewer
- [x] Test it: /test full repository context code reviewer
- [x] Review it (fresh model): /check review full repository context code reviewer
- [x] Document it: /document full repository context code reviewer

## Slice 3: Live task streaming & interactive collaboration

### 7. Live task streaming & interactive collaboration
Stream live sandbox logs and agent decisions to the web console, allowing developers to answer questions mid task, give guidance, or take over execution.
**Done when:** developers can watch live task execution in the web console, send instructions while the agent runs, and take control when needed.
spec [0006](../specs/0006-live-task-streaming-and-interactive-collaboration/index.md) · code in `apps/agent/`, `apps/web/`
- [x] Design it (spec): `/architect live task streaming & interactive collaboration`
- [x] Build it: /develop live task streaming & interactive collaboration
  - [x] Database migration for task interruption state, task_interventions, and task_transcripts (AC-1, AC-4)
  - [x] Redis Streams event appender, in flight log reader, and post task completion transcript archiver (AC-1, AC-5)
  - [x] FastAPI Server Sent Events endpoint with Last-Event-ID cursor replay and keep alive ping comments (AC-1)
  - [x] LangGraph human in the loop interrupt state machine, E2B timeout extension, and delayed queue watchdog (AC-4)
  - [x] Web console useTaskStream hook, split pane execution inspector, and REST intervention endpoints (AC-2, AC-3, AC-4)
- [x] Verify it: /check verify live task streaming & interactive collaboration
- [x] Test it: /test live task streaming & interactive collaboration
- [x] Review it (fresh model): /check review live task streaming & interactive collaboration
- [x] Document it: /document live task streaming & interactive collaboration

## Slice 4: Guardrails, branch protection & budget limits

### 8. Guardrails, branch protection & budget limits
Enforce least privilege repository access, block direct pushes to protected branches, require human approvals for risky actions, and enforce task runtime and spending caps.
**Done when:** risky actions pause for human approval, protected branches reject direct pushes, and tasks halt when spending or time limits are reached.
spec [0008](../specs/0008-guardrails-branch-protection-and-budget-limits/index.md) · code in `apps/agent/`, `apps/web/`
- [x] Design it (spec): `/architect guardrails, branch protection & budget limits`
- [x] Build it: /develop guardrails, branch protection & budget limits
  - [x] Database migration, PolicyEvaluator, and ceiling cent UsageTracker core (AC-1, AC-2, AC-3, AC-5, AC-6)
  - [x] Least privilege GitHub token split, sandbox pre-push hook, and host branch guard (AC-2)
  - [x] LangGraph host publish node, idempotent approval interrupts, and budget/runtime halts (AC-2, AC-3, AC-4, AC-5, AC-6)
  - [x] Guardrails, usage, repository override, and approval decision REST endpoints (AC-1, AC-4, AC-5)
  - [x] Sandbox egress network isolation and console UI settings, repo drawer, and task approval/cost views (AC-7)
- [x] Verify it: /check verify guardrails, branch protection & budget limits
- [x] Test it: /test guardrails, branch protection & budget limits
- [x] Review it (fresh model): /check review guardrails, branch protection & budget limits
- [x] Document it: /document guardrails, branch protection & budget limits

## Slice 5: Custom review rules & feedback learning

### 9. Custom review rules & feedback learning
Enable teams to configure written review guidelines and example pull requests, learn from accepted or dismissed feedback, and display team quality and turnaround metrics.
**Done when:** teams can configure repository specific guidelines, review suggestions adapt to dismiss history, and the console reports turnaround and cost metrics.
spec [0009](../specs/0009-custom-review-rules-and-feedback-learning/index.md) · code in `apps/agent/`, `apps/web/`
- [x] Design it (spec): `/architect custom review rules & feedback learning`
- [x] Build it: `/develop custom review rules & feedback learning`
  - [x] Database migrations, Spec 0005 schema backfill, and ReviewContextService core (AC-1, AC-2, AC-4, AC-7)
  - [x] Tier 1 bounded prompt injection across PR reviews and Forge reviewer loop (AC-4, AC-5)
  - [x] GitHub comment ID backfill, console feedback endpoint, and gated webhook ingestion (AC-3, AC-4)
  - [x] Rules, examples, preferences, reviews, and SQL analytics REST endpoints (AC-1, AC-2, AC-4, AC-6, AC-7)
  - [x] Console UI for /analytics, /reviews, /settings guidelines, and /repositories drawer tabs (AC-7)
- [x] Verify it: `/check verify custom review rules & feedback learning`
- [x] Test it: `/test custom review rules & feedback learning`
- [x] Review it (fresh model): `/check review custom review rules & feedback learning`
- [x] Document it: `/document custom review rules & feedback learning`

## Deferred
Out of scope for the current build pass, kept so the plan stays honest.
- **Commercial subscription billing and credit metering**: usage metering with automated invoices and card payments · needs a decision
- **Additional code hosts**: GitLab and Bitbucket repository connectors · needs a decision
- **External ticketing integrations**: Linear and Jira issue synchronization · needs a decision
- **Team chat integrations**: Slack and Microsoft Teams notification and trigger bots · needs a decision
- **Enterprise customer infrastructure packaging**: Helm charts and private cluster deployment bundles · needs a decision

## Legend

**The decision box.** Every feature carries exactly one, the subtask whose label ends with `(spec)`. Its wording varies (`Design it (spec)` normally, `Decide the stack (spec)` on Stack & architecture), so skills locate it by that `(spec)` suffix, never by an exact label. Every other box is an execution box and `/architect` never ticks one.

**Feature lifecycle**: the scope updates as a feature moves; each row is what it shows and who sets it:

| State | Set by | The feature shows |
|---|---|---|
| `planned` · needs a decision | `/scope` | one box: `Design it (spec): /architect <feature>` |
| `in-progress` (designed) | **`/architect` at spec capture** | `Design it` ticked; spec linked; `Build it: /develop <feature>` + **2 to 5 milestones**; the tier closing boxes (`Verify it` Alpha+, `Test it` Beta+, `Review it` + `Document it` GA); any surfaced follow up enrolled |
| `in-progress` (building) | `/develop` | milestone sub boxes tick one by one; code pointer filled |
| `in-progress` (verified) | `/check verify` | `Build it` + milestones ticked; `Verify it` ticked |
| `done` | **you, when you decide it is** (any skill sets it when you say so); `/sync` reconciles | boxes you ran ticked, skipped ones marked skipped; the tier last stage (`Prototype` → after `/develop`; `Alpha` → after `/check verify`; `Beta`/`GA` → after `/test`) is the suggested point to call it done; `/sync` captures conventions |

- **Next step** = the first unticked box (always a command or a tracked milestone).
- **needs a decision** = run `/architect` first; otherwise straight to `/develop` (or `/audit` for standards & tooling). The tag drops once the spec is captured.
- **Atomic build tasks live in the spec's `## Build plan`, not here**: the scope carries only the milestone rollup.
- **Status** `planned` → `in-progress` → `done`, plus `existing` (pre workflow) and `dropped` (dropped from scope, kept for history).
- **Approach tag** beside a heading (e.g. `· Facade`) overrides the project default for that feature; no tag = inherits it.
- **Workflow tier tag** beside a heading (e.g. `· GA`, `· Prototype`) sets that one feature's rigor above or below the project default; no tag inherits the default. It decides the feature check boxes and each skill next suggestion.
- **Workflow** (header line) is the project default, what runs after `/develop`: **Prototype** = nothing (trust develop build time self check); **Alpha** = `/check verify`; **Beta** = `/check verify` then `/test`; **GA** = adds a fresh model `/check review` then `/document`. A feature built on an unratified decision (an `Assumed` spec) stays flagged, but that never blocks `done`.
- **Pointer line** (`spec <n> · code in <path>`): the spec link added by `/architect`, the code path by `/develop`.
