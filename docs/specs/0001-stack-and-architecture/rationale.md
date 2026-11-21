# 0001. Stack and architecture: Rationale and Decision Record

## Context

agentsOnAir is an autonomous software engineering and code review platform. The system takes tasks from GitHub events, plans modifications, writes code, runs test suites, performs independent reviews, and opens pull requests. This workload introduces unique architectural forces that standard web applications do not face.

First, executing agent generated code requires secure isolation. Running arbitrary code, shell commands, or package installations directly on host containers creates container breakout risks. The platform must provide hardware level isolation with fast subsecond startup times so agents can iterate quickly without risking host infrastructure.

Second, agent decision loops are stateful and cyclical. An autonomous developer plans, writes code, encounters test failures, reflects on errors, and iterates until tests pass. If an agent step stalls or fails mid task, the system must recover from the last safe checkpoint without losing progress or corrupting task state.

Third, the platform serves two distinct user interfaces. Developers interact through a reactive web console to observe live streaming agent actions and intervene when needed. At the same time, the backend must interface with GitHub webhooks, run scheduled background jobs, and manage multi tenant access across organizations.

Failing to decide these foundational layers now would lead to fragmented tooling, mismatched communication contracts, and security vulnerabilities during task execution.

## Options considered

### Option 1: Polyglot monorepo with Next.js web console and Python FastAPI agent engine

This option organizes the codebase as a Turborepo monorepo. The web console lives in `apps/web` using Next.js App Router and Tailwind CSS. The agent engine lives in `apps/agent` using Python 3.12, FastAPI, and LangGraph. State coordination uses PostgreSQL for relational data and checkpoints, Redis with ARQ for worker task queues, and E2B microVMs for isolated code execution.

**Pros**:
* Combines the best of React Server Components and modern web UX with the mature Python AI agent ecosystem
* LangGraph provides native state graph coordination, cyclical loops, and checkpointing out of the box
* Clear process separation ensures compute heavy agent execution never blocks web console responsiveness

**Cons**:
* Requires managing both Node.js and Python toolchains in local development and continuous integration
* Data types between TypeScript and Python must be synchronized via schemas or code generation

### Option 2: Unified full stack TypeScript on Next.js with embedded agent worker

This option runs the entire platform within a unified TypeScript codebase using Next.js, Node.js worker threads or LangGraph.js, and Prisma with PostgreSQL.

**Pros**:
* Single programming language across web console, API routes, and agent loops
* Seamless type sharing between front end components and agent data structures without translation layers
* Simpler onboarding and continuous integration pipeline for JavaScript engineers

**Cons**:
* The JavaScript AI and machine learning ecosystem is smaller and moves slower than Python
* Complex code evaluation, Abstract Syntax Tree analysis, and future custom model integrations are more cumbersome in Node.js

### Option 3: Python monolithic service with Django and server rendered templates

This option builds a Python monolith using Django or FastAPI with server rendered templates using Jinja or HTMX, minimizing JavaScript usage across the project.

**Pros**:
* Single language and unified framework for both database modeling and agent execution
* Eliminates separate API translation layers and cross service authentication complexity

**Cons**:
* Server rendered templates struggle to deliver the highly interactive, terminal like streaming experience required for live task collaboration
* Significantly smaller front end component ecosystem for complex developer dashboards

## Rationale

Option 1 provides the best balance between developer experience, operational safety, and system capabilities (basis: your scope Tracer Bullet approach).

Building autonomous coding agents requires continuous experimentation with agent loops, prompt graphs, tool calling, and evaluation harnesses. Python is the undisputed center of gravity for AI agent tooling, making LangGraph in Python the natural engine for cyclical self correction loops (basis: cyclical graph state pattern).

At the same time, the web console demands a modern, component driven interface with streaming capabilities so engineers can watch agent progress, view side by side diffs, and intervene in real time (basis: Server Sent Events streaming). Next.js provides modern server rendering, streaming, and Tailwind CSS primitives that far exceed what server rendered Python templates offer.

For security, E2B cloud microVMs deliver hardware level Firecracker isolation in roughly 150 milliseconds (basis: microVM hardware isolation). This eliminates the threat of malicious code escaping shared host kernels, fulfilling our core requirement for untrusted sandbox execution.

Turborepo keeps both workspaces in a single repository, allowing coordinated pull requests, shared configuration, and unified continuous integration while preserving clear runtime separation.

## References

**Project sources**:
* `docs/scope/scope.md`: Feature 1 and Tracer Bullet foundation
* `.agents/skills/nextjs-app-router-patterns/`: Next.js App Router conventions
* `.agents/skills/fastapi-templates/`: FastAPI project structure and async routing
* `.agents/skills/clerk-nextjs-patterns/`: Clerk authentication and organization management

**Practices & standards**:
* MicroVM hardware isolation for untrusted code execution
* Single writer database pattern for relational integrity
* Redis Pub/Sub event bridge for real time log streaming
* Cyclical graph state pattern for autonomous agent loops
* Server Sent Events for low latency log streaming
* Relational ACID persistence for agent run history and checkpointing
* Monolith before microservices for operational simplicity

**Links**:
* E2B Sandboxes: https://e2b.dev
* Vercel AI SDK and Sandbox: https://github.com/vercel/ai
* LangGraph Documentation: https://langchain-ai.github.io/langgraph
* FastAPI Documentation: https://fastapi.tiangolo.com
* Next.js Documentation: https://nextjs.org
