# 0009. Rationale: custom review rules and feedback learning

## Context

AgentsOnAir already performs full repository context pull request reviews (Spec 0005) and runs an internal Forge and Reviewer loop during autonomous tasks (Spec 0004). Today, those reviews rely solely on repository `AGENTS.md` files and generic engineering heuristics. Teams have no structured way to express repository specific rules, show the reviewer examples of preferred pull requests, or silence recurring false positives when engineers dismiss comments on GitHub.

At the same time, engineering leaders lack visibility into whether autonomous reviews and engineering tasks are improving turnaround or wasting AI budget on noisy suggestions. Token costs are already captured per call in `usage_events` (Spec 0008), and findings are stored in `pr_review_findings` (Spec 0005), but nothing links dismissed findings back into future prompts or surfaces turnaround, acceptance rate, and split spend in the web console.

Several constraints shape the design:
- Spec 0005 caps the code review prompt at 64,000 tokens (32,000 for Tier 1 diff hunks and project instructions, 28,000 for Tier 2 symbol context, 4,000 reserve). Adding arbitrary guidelines and example diffs cannot blow past that window or crowd out the actual code diff.
- GitHub webhooks deliver thread resolution (`pull_request_review_thread`) and comment replies (`pull_request_review_comment`), but do not fire webhooks for emoji reactions. Moreover, external fork contributors on public repositories can post arbitrary reply comments, so feedback capture must guard against prompt poisoning.
- Organization admins need tight governance over shared review standards and budget impacting prompt content, while individual developers still need fast, low friction ways to dismiss unhelpful comments.

## Options considered

### Option 1: Relational review rules, deterministic glob and overlap selection inside Tier 1, dual channel feedback memory, and direct SQL analytics

Store organization default rules (with soft deletes), repository overrides, curated example pull requests (with extracted `modified_files`), immutable feedback events, and learned preferences in PostgreSQL tables. Select relevant rules via a globstar aware matcher, rank example PRs by modified file overlap, and pack them into a bounded 6,000 token sub budget inside Tier 1 alongside learned preferences with XML angle bracket escaping. Capture feedback from console actions and `author_association` gated GitHub webhooks, automatically dampening at 2 dismissals and suppressing at 3 consecutive dismissals, and serve Analytics directly from indexed SQL queries to lightweight SVG charts in Next.js.

**Pros**:
- Zero new infrastructure (no `pgvector`, embedding API calls, cron reaction pollers, or separate analytics rollup pipeline).
- Deterministic, inspectable selection makes it easy to test and explain why a rule or example appeared in a review.
- Enforces hard token caps so custom guidelines and examples never starve the PR diff.

**Cons**:
- Path glob and directory level `pattern_key` matching cannot match semantic similarity across unrelated file paths.
- Keyword based reply matching on GitHub requires explicit phrases (`dismiss`, `false positive`, `good catch`) alongside thread resolution.
- Direct SQL percentile queries require composite indexes and multi table joins when filtering by `repo_id`.

### Option 2: Vector embeddings (`pgvector`) with nightly metrics rollup tables and GitHub reaction polling

Embed every rule, example PR diff, and feedback memory using an external embedding model into PostgreSQL `pgvector`, poll GitHub reactions on a schedule to capture thumbs up/down signals, and precompute daily metrics in a separate rollup table.

**Pros**:
- Captures semantic similarity between feedback and new code even when file paths differ.
- Precomputed rollup tables keep dashboard reads constant time regardless of historical volume.

**Cons**:
- Adds embedding API latency, external key dependency, and `pgvector` extension management for at most 25 rules and 5 examples per repository.
- Periodic GitHub reaction polling consumes installation rate limits and introduces delayed feedback state.
- Rollup jobs add synchronization complexity and stale data edge cases.

### Option 3: Repository checked in markdown files only with console only feedback and static tables

Read custom rules exclusively from a committed `.agentsonair/review.md` file in each repository, inject the full file verbatim into prompts, capture feedback only in the web console, and render Analytics as summary tables without charts.

**Pros**:
- Rules are versioned in git alongside application code.
- Minimal backend schema changes and zero webhook additions.

**Cons**:
- Teams lose centralized `org:admin` governance, per rule severity overrides, and rule level effectiveness tracking.
- Engineers rarely leave GitHub PRs to click feedback buttons in a separate console, starving the feedback loop.
- Unstructured markdown makes per rule dampening and suppression impossible without brittle text rewriting.

## Rationale

Option 1 fits the project's **Tracer Bullet** philosophy and existing PostgreSQL, FastAPI, LangGraph, and Next.js stack without introducing new operational dependencies. With a 25 active rule cap and 5 example PR cap per repository, deterministic globstar path matching and stored `modified_files` overlap ranking solve selection at near zero latency and cost, avoiding `pgvector` and embedding calls for a small rule set.

Restricting rule, example PR, and preference edits to `org:admin` matches the governance model already established in Spec 0007 and Spec 0008, ensuring only admins alter prompt inputs that affect review strictness and token spend, while gating GitHub webhook feedback to `OWNER`, `MEMBER`, and `COLLABORATOR` associations prevents external fork commenters from poisoning team memory. Sharing merged rules and learned preferences across both `RunPRReviewUseCase` (Spec 0005) and `task_graph.py`'s internal `reviewer_node` (Spec 0004) ensures autonomous pull requests follow the exact same team standards as human pull requests before reaching GitHub. Finally, querying indexed source tables (`pull_request_reviews`, `pr_review_findings`, `task_runs`, `usage_events`) directly keeps analytics accurate and simple on day one, with optional short Redis caching ready if organization volume grows.
