# Scope: agentsOnAir

An autonomous software engineering and code review platform that develops, tests, and verifies code in isolated sandboxes before opening verified pull requests.

**Build approach:** Tracer Bullet (prove the whole loop works end to end through every layer before broadening features).
**Workflow:** GA (after develop, run check verify, automated tests, a fresh reviewer check, and document). The project default level of rigor. `/architect` is the recommended first stop for a feature with a real decision, but skippable when you already know the build. Any feature can carry its own tag to do more or less.

_These are recommendations to keep your build orderly, not requirements. Skip anything that does not fit: if you already know how to build a feature, use `/develop` and skip `/architect`. You decide when a feature is `done`._

## At a glance

| # | Feature | Phase | Status |
|---|---------|-------|--------|
| 1 | Stack & architecture | Foundation | in-progress |
| 2 | Coding standards & tooling | Foundation | planned |
| 3 | Data model | Foundation | planned |
| 4 | Design system & console UI foundation | Foundation | planned |
| 5 | Core autonomous engineer and reviewer loop | Slice 1 | planned |
| 6 | Full repository context code reviewer | Slice 2 | planned |
| 7 | Live task streaming & interactive collaboration | Slice 3 | planned |
| 8 | Guardrails, branch protection & budget limits | Slice 4 | planned |
| 9 | Custom review rules & feedback learning | Slice 5 | planned |

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
- [ ] Capture conventions and tooling choices: `/audit`
- [ ] Install the tooling: `/develop tooling`
- [ ] Check it runs clean: `/test`

### 3. Data model · needs a decision
Core database schema for tenant organizations, repositories, agent tasks, sandbox runs, audit logs, and encrypted credentials.
**Done when:** entities and migrations support task execution, tenant isolation, and audit events without breaking changes.
- [ ] Design it (spec): `/architect data model`

### 4. Design system & console UI foundation · needs a decision
Visual design tokens, layout primitives, and reusable UI components for the web console so developers can inspect tasks and configure settings.
**Done when:** design tokens define colors, typography, layout, and accessible base components support keyboard and screen navigation.
- [ ] Design it (spec): `/architect design system & console UI foundation`

## Slice 1: Core autonomous engineer and reviewer loop

### 5. Core autonomous engineer and reviewer loop · needs a decision
Connect the initial working thread through every layer: a GitHub task trigger starts an isolated sandbox, forge writes code and runs tests against a mock repository and mock model harness, the independent reviewer checks the diff, forge applies fixes, and opens a verified GitHub pull request.
**Done when:** an issue or webhook triggers a task, runs in an isolated sandbox, passes autonomous review, and opens a pull request with changelog and audit trail.
- [ ] Design it (spec): `/architect core autonomous engineer and reviewer loop`

## Slice 2: Full repository context code reviewer

### 6. Full repository context code reviewer · needs a decision
Review pull requests authored by humans or agents by reading the full repository context, ranking issues by severity, and posting line comments and suggested fixes.
**Done when:** a pull request triggers a review that analyzes repository context beyond the diff, ranks findings by severity, and posts actionable comments to GitHub.
- [ ] Design it (spec): `/architect full repository context code reviewer`

## Slice 3: Live task streaming & interactive collaboration

### 7. Live task streaming & interactive collaboration · needs a decision
Stream live sandbox logs and agent decisions to the web console, allowing developers to answer questions mid task, give guidance, or take over execution.
**Done when:** developers can watch live task execution in the web console, send instructions while the agent runs, and take control when needed.
- [ ] Design it (spec): `/architect live task streaming & interactive collaboration`

## Slice 4: Guardrails, branch protection & budget limits

### 8. Guardrails, branch protection & budget limits · needs a decision
Enforce least privilege repository access, block direct pushes to protected branches, require human approvals for risky actions, and enforce task runtime and spending caps.
**Done when:** risky actions pause for human approval, protected branches reject direct pushes, and tasks halt when spending or time limits are reached.
- [ ] Design it (spec): `/architect guardrails, branch protection & budget limits`

## Slice 5: Custom review rules & feedback learning

### 9. Custom review rules & feedback learning · needs a decision
Enable teams to configure written review guidelines and example pull requests, learn from accepted or dismissed feedback, and display team quality and turnaround metrics.
**Done when:** teams can configure repository specific guidelines, review suggestions adapt to dismiss history, and the console reports turnaround and cost metrics.
- [ ] Design it (spec): `/architect custom review rules & feedback learning`

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
