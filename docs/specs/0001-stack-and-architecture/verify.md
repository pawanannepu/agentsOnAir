# Verify: Stack & architecture · spec 0001 · updated 2026-11-21
_Steps derived from spec 0001 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [x] Open http://localhost:3000 in browser → Next.js console landing page renders with active monorepo status → AC-1
- [x] Open http://localhost:8000/api/v1/health in browser → returns healthy json payload from FastAPI → AC-1

## Commands
- [x] `pnpm install` → completes cleanly and links workspace packages `web` and `agent` → AC-1
- [x] `pnpm build` → compiles Next.js with Turbopack and builds agent package → AC-1
- [x] `pnpm test` → runs pytest for `apps/agent` (2 passed) and web test runner → AC-1
- [x] `(cd apps/agent && uv run pytest)` → FastAPI health endpoint tests pass in 0.01s → AC-1
- [x] `pnpm --filter web typecheck` → TypeScript compiler typechecks cleanly with no errors → AC-1

## Acceptance-criteria coverage
- AC-1 (the stack is recorded in a spec, and the empty scaffold builds, passes tests, and runs locally) covered by all steps above
