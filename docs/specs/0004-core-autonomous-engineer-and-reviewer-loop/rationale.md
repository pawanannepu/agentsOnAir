# 0004. Rationale: Core autonomous engineer and reviewer loop

## Context

Software engineering teams lose substantial time triaging straightforward bug fixes, writing repetitive boilerplate, and reviewing trivial code errors. Existing coding assistants either operate synchronously inside developer editors or produce unchecked pull requests that fail continuous integration pipelines and require tedious human clean up. 

To deliver reliable autonomous engineering, agentsOnAir needs a robust execution loop that can ingest an issue, isolate repository code inside a secure sandbox, write implementations, run local tests, critique the resulting diff, and iterate until the change meets quality standards. The loop must operate autonomously while enforcing strict boundaries: preventing runaway spend, avoiding infinite repair loops, protecting repositories from unauthorized pushes, and maintaining an immutable audit history of every decision.

Without a deliberated loop architecture, the agent risks either submitting hallucinated, broken code directly to GitHub, or spinning in costly unconstrained repair loops when tests fail. Slicing this capability as our first tracer bullet proves the complete end to end path from webhook trigger to opened pull request across all system layers.

## Options considered

### Option 1: Cyclical two agent state graph with Forge inner tool loop and Reviewer critic (Recommended)

In this design, LangGraph manages a state machine featuring two distinct agent roles. Forge acts as the implementation engineer with access to file tools, shell execution, and test runners inside an isolated sandbox, iterating internally in a ReAct loop to author and test changes. Reviewer acts as an independent critic with zero temperature, analyzing the git diff and test logs against the original issue requirements. If Reviewer detects blocking defects (critical or major severities), control returns to Forge along with structured findings. The outer cycle repeats up to a strict limit of 3 iterations before opening a verified pull request or terminating with a diagnostic failure.

To maintain security, write tokens never enter the sandbox. The host runner extracts the diff, verifies patch boundaries, commits as `agentsonair[bot]`, and pushes to GitHub. A baseline test pass on the base branch runs before Forge edits, ensuring pre existing failures are not attributed to the agent.

**Pros**:
* Independent reviewer catches regressions, logic bugs, and syntax errors before code reaches human reviewers.
* Inner tool loop allows iterative coding and test execution without consuming outer review cycle limits.
* Credential isolation keeps repository write keys on the host, preventing sandbox escapes from stealing privileges.
* Bounded cyclical graph provides automatic self healing while capping token spend and latency.

**Cons**:
* Multi agent loops consume more tokens than single pass generation.
* Requires host side diff extraction and verification logic.

### Option 2: Single agent self critique loop

In this design, a single agent model carries out coding, runs sandbox tests, and prompts itself to critique its own diff in subsequent steps before committing and pushing.

**Pros**:
* Simpler graph definition with fewer node transitions and lower prompt overhead.
* Fast initial delivery with minimal orchestration logic.

**Cons**:
* Models suffer from confirmation bias when evaluating their own code, frequently missing the same bugs they introduced.
* Blurring synthesis and critique roles degrades evaluation rigor and leads to false approvals.

### Option 3: Linear pipeline with single pass review gate and no retries

In this design, Forge writes code and runs tests once. A Reviewer node performs a final check. If approved, the pull request opens. If rejected, the task fails immediately without retrying.

**Pros**:
* Predictable execution time and minimal token cost per task run.
* Simple linear control flow with no cyclical states.

**Cons**:
* Any minor linting error or test failure causes immediate task failure, resulting in poor completion rates.
* Lacks self healing capability, forcing humans to intervene on trivial fixes.

## Rationale

We choose Option 1 because autonomous software engineering requires both active implementation capabilities and rigorous, independent verification. Relying on a single agent to critique its own code leads to confirmation bias where hallucinated assumptions go unchallenged. Conversely, a linear pipeline without fix iterations fails on minor formatting or compilation errors that an engineer would resolve in seconds.

The cyclical two agent topology mirrors high performing human engineering pairs: an author who writes code and tests, and a reviewer who verifies that requirements are met and tests pass. Separating the inner tool loop (where Forge refines edits and runs local tests) from the outer review loop ensures that trivial syntax adjustments do not prematurely exhaust the 3 cycle cap. Isolating git write credentials to the host worker protects customer repositories against credential extraction by untrusted code running during test suites.
