# Verify: Live task streaming and interactive collaboration · spec 0006 · updated 2026-11-24
_Steps derived from spec 0006 acceptance criteria. /check verify runs these; /test locks the durable ones._

## UI and manual
* [x] Open an in progress task in the web console (`/tasks/{task_id}`) -> live Server Sent Events connection opens to FastAPI and terminal logs render in virtualized TerminalViewer with ANSI colors and autoscroll -> AC-1, AC-2
* [x] Disconnect network or refresh page while task is active -> client reconnects using Last-Event-ID header and replays missed chunks from Redis Streams without duplicate lines -> AC-1, AC-5
* [x] Submit developer guidance via intervention input bar (`POST /api/v1/tasks/{task_id}/intervene`) -> message persists in task_interventions table and agent worker consumes it before next step -> AC-3
* [x] Agent yields clarification interrupt -> task transitions to awaiting input status, sandbox timeout extends, worker process releases, web console displays prompt banner, user submits answer, and agent resumes sandbox execution -> AC-3, AC-4
* [x] Task enters awaiting input and developer does not answer within 15 minutes -> delayed queue watchdog marks task failed with timeout reason and halts sandbox resources -> AC-4
* [x] Two users submit answers to the same awaiting input prompt simultaneously -> first submission returns 200 OK, second submission receives 409 Conflict -> AC-3
* [x] Poll `GET /api/v1/tasks/{task_id}/transcript` while task is in progress -> returns current accumulated logs from Redis Streams -> AC-5
* [x] Task finishes execution -> Redis events consolidate into gzip compressed task_transcripts record in PostgreSQL, and GET /transcript returns full logs -> AC-5
* [x] Open `/tasks/{task_id}` while signed in with Clerk (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` configured) -> `ClerkTaskDetail` supplies `orgId` and `getToken`, SSE connects with Bearer token, and an `awaiting_input` task hydrates its clarification banner on initial load -> AC-2, AC-3
* [x] Open `/tasks/{task_id}?org_id={org_id}` on a completed task or when SSE fails -> `TaskDetailClient` hydrates terminal logs from `GET /api/v1/tasks/{task_id}/transcript` -> AC-5

## Commands
* [x] `uv run pytest tests/test_task_streaming.py -v` -> verifies SSE endpoint, Redis Streams XREAD BLOCK cursor replay, LangGraph interrupt state machine, and intervention endpoints -> AC-1, AC-3, AC-4, AC-5
* [x] `pnpm --filter web test` -> verifies useTaskStream client hook, TerminalViewer integration, and intervention input components -> AC-2, AC-3
* [x] `pnpm typecheck && pnpm lint` -> zero errors across web and agent packages -> AC-1..AC-5
* [x] `uv run alembic current` -> shows migration `a7d92f4c1b80 (head)` applied for task interruption state, `ck_tasks_status` check constraint, `task_interventions`, and `task_transcripts` -> AC-1, AC-4, AC-5

## Acceptance criteria coverage
* AC-1: Server Sent Events endpoint with Redis Streams XREAD BLOCK cursor replay and keep alive comments covered by `tests/test_task_streaming.py::test_sse_events_and_cursor_replay`.
* AC-2: Web console streaming client hook and virtualized TerminalViewer ANSI rendering covered by `apps/web/tests/task_stream.test.tsx`.
* AC-3: Authenticated REST intervention endpoints for steering guidance, clarification responses, and abort commands with optimistic concurrency covered by `tests/test_task_streaming.py::test_task_interventions_and_concurrency`.
* AC-4: LangGraph human in the loop interrupt state machine, worker process release, E2B timeout extension, and delayed queue timeout watchdog covered by `tests/test_task_streaming.py::test_langgraph_interrupt_and_timeout`.
* AC-5: Capped Redis Streams buffer, in flight transcript fallback, and post task completion transcript archival with gzip compression covered by `tests/test_task_streaming.py::test_transcript_archival_and_compression`.
