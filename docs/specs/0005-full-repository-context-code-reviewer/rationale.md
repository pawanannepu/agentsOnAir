# 0005. Full repository context code reviewer: Rationale

## Context

Pull requests are the primary quality gate in modern software development. While basic continuous integration tools run linters and unit test suites on modified files, human reviewers spend considerable time identifying subtle bugs, interface mismatches, missing error checks, and violations of project conventions. Standard automated code review bots often analyze only the raw git diff in isolation. Because they lack repository context, they fail to detect breaking changes in callers, stale interface assumptions, or conflicting architectural rules across modules.

At the same time, naive attempts to supply repository context by dumping entire codebases into large language model prompts lead to context window exhaustion, high financial cost, and degraded reasoning accuracy. In addition, automated reviewer bots frequently suffer from infinite feedback loops when reviewing automated pull requests created by other bots or themselves. Furthermore, rapid code pushes often trigger duplicate concurrent reviews, while strict GitHub API line rules can cause entire batch reviews to fail if line numbers drift.

To deliver effective automated code reviews for agentsOnAir, we need a reviewer that extracts relevant repository context beyond the diff, respects token budgets, formats actionable inline suggestions on GitHub, guards against concurrency races, and cleanly excludes bot feedback cycles.

## Options considered

### Option 1: Hybrid symbol graph context expansion with tree-sitter parsing and unified GitHub review submissions

Use tree-sitter to parse modified files and build a local symbol graph of direct callers, callees, and enclosing types from a shallow tarball. A two tier context allocator packs the git diff hunks and high priority symbol context into a bounded 64k token prompt window (Tier 1 core diff up to 32k, Tier 2 symbol graph up to 28k, 4k reserve). Claude Sonnet analyzes the code using structured output schemas and posts a single GitHub pull request review containing inline diff comments for diff lines, summary notes for out of diff concerns, and a resilient 422 fallback.

**Pros**:
* Fast, native incremental parsing across TypeScript, Python, and other major languages without running language specific compilers.
* Precise structural context (callers, callees, signatures) without noisy text embeddings.
* Unified GitHub review submission minimizes notification spam and provides one click suggestions.
* Concurrency protection via active review partial unique index avoids wasted spend on rapid pushes.

**Cons**:
* Requires shipping native tree-sitter grammar binaries inside the agent container.
* Graph expansion is bounded to direct call hierarchies rather than deep multi hop dependency traversal.

### Option 2: Full text vector database embeddings with semantic retrieval

Index the entire repository into vector embeddings and retrieve the top nearest neighbor text chunks for each modified line in the pull request diff.

**Pros**:
* Flexible natural language retrieval across documentation, comments, and code.
* Uses generic vector database infrastructure without needing language specific parsers.

**Cons**:
* Poor structural precision for code dependencies; vector similarity often retrieves superficially similar functions rather than actual callers or type definitions.
* High indexing latency and cost to re embed repository content on every commit.

### Option 3: Shallow diff only review with direct file imports

Analyze only the files present in the pull request diff, expanding context solely by reading the direct file level import statements.

**Pros**:
* Minimal implementation complexity and zero parsing overhead.
* Fast execution turnaround.

**Cons**:
* Blind to callers in other files that invoke modified functions, missing downstream regressions.
* Frequently runs out of context if imported files are large, or misses dependencies when imports are indirect.

## Rationale

Option 1 is selected because it directly addresses the core limitation of diff only review bots while keeping token usage and execution latency under control. By using tree-sitter, we extract genuine structural relationships (callers, callees, type signatures) rather than fuzzy text matches from a vector database (Option 2) or superficial whole file imports (Option 3).

Bounding the context window to 64k tokens partitioned into Tier 1 (core diff) and Tier 2 (symbol graph) ensures predictable operational costs and prevents model distraction on large pull requests. A shallow tarball download avoids heavy git clone overhead on customer repositories. Submitting a single GitHub review with inline suggestions provides the best user experience for developers, while routing out of diff findings to the review summary and providing an automatic 422 fallback prevents GitHub API rejection errors. Concurrency protection via an active review partial unique index guarantees that rapid synchronize webhooks do not double model spend or post duplicate reviews.
