# Verify: design system & console UI foundation · spec 0003 · updated 2026-11-22

_Steps derived from spec 0003 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
* [x] Visit `/` in browser → verify dark theme loads with mission control metrics and recent task list → AC-1, AC-6
* [x] Navigate to `/tasks` → click filter tab "Running", verify only running tasks appear with active pulse badge → AC-2, AC-6
* [x] Navigate to `/tasks/018f6c38-8921-7000-8000-000000000001` → verify split view with metadata card on left and live TerminalViewer on right → AC-3, AC-6
* [x] In TerminalViewer, verify ANSI colors render properly, auto scroll pins to bottom on stream, and scrolling up disengages pin showing floating "Scroll to bottom" button → AC-3
* [x] In TerminalViewer, click "Copy" button, verify clipboard content contains clean plain text without raw ANSI escape codes → AC-3
* [x] Press `Cmd+K` or `Ctrl+K` anywhere in console → verify command dialog opens with focus trapped, type "repositories" and press Enter, verify navigation to `/repositories` → AC-5
* [x] On `/settings`, change sandbox provider to "Local Docker Engine", click Save, verify Sonner toast notification appears → AC-4
* [x] Click collapse button on sidebar footer → verify sidebar collapses to 64px icon only mode and sets `aoa_sidebar_state=collapsed` cookie → AC-6

## Commands
* [x] `pnpm --filter web typecheck` → passes with 0 errors → AC-1, AC-2
* [x] `pnpm --filter web lint` → passes with 0 errors → AC-1, AC-2
* [x] `pnpm --filter web test` → passes with 23 of 23 tests green → AC-2, AC-3
* [x] `pnpm --filter web build` → Next.js Turbopack production build succeeds with all routes prerendered → AC-1, AC-6

## Acceptance criteria coverage
* AC-1 (Tailwind v4 tokens & dark theme) covered by globals.css theme tokens and build command
* AC-2 (Accessible base CVA components) covered by button, badge, card, dialog, table unit tests and `/tasks` UI
* AC-3 (Streaming virtualized TerminalViewer) covered by TerminalViewer tests and `/tasks/[id]` live stream view
* AC-4 (Toast notification system) covered by Sonner toaster provider and settings save toast step
* AC-5 (Global command palette) covered by CommandDialog palette and keyboard shortcut step
* AC-6 (Console application shell) covered by ConsoleLayout, Sidebar, Header, and route views
