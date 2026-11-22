# 0003. Design system and console UI foundation

**Date**: 2026-11-22
**Status**: Accepted

## Summary

This specification defines the visual design system tokens, accessible UI component library, and console layout shell for the agentsOnAir web console. We build a dark theme developer interface using Tailwind CSS v4 CSS first theme tokens, Radix UI accessible primitives, Class Variance Authority (CVA), and Lucide icons. The foundation provides core building blocks, a high performance virtualized terminal viewer for streaming logs, a global command palette, and a collapsible application shell for task inspection. This gives developers a fast, accessible, and information dense experience when monitoring autonomous agent runs.

## Requirements

**User stories**:
* As a software engineer, I want an information dense and accessible console interface so that I can inspect active agent tasks, read streaming terminal logs, and review diffs comfortably.
* As an operator, I want a global command palette and keyboard shortcuts so that I can navigate quickly between tasks, repositories, and workspace settings without using a mouse.
* As a developer running long tasks, I want streaming terminal logs with auto scroll pinning and ANSI color rendering so that I can follow agent execution in real time without browser lag or memory exhaustion.

**Acceptance criteria**:
* **AC-1**: Design tokens define semantic OKLCH colors, Geist typography scales, compact spacing, and border radius in Tailwind CSS v4 theme variables, establishing a zinc neutral dark theme by default.
* **AC-2**: Base interactive components (Button, Badge, Card, Dialog, Tabs, Table, Input, Select) built on Radix UI primitives and Class Variance Authority enforce WCAG AA accessibility, visible focus rings, and full keyboard navigation.
* **AC-3**: Streaming terminal log component (TerminalViewer) renders streaming lines with virtualized rendering via `@tanstack/react-virtual`, ANSI color formatting via `ansi-to-react`, auto scroll pinning, search filter, line numbering, and clean clipboard copy actions without ANSI escape characters.
* **AC-4**: Toast notification system powered by Sonner provides asynchronous feedback for task status transitions, background errors, and copy actions styled with theme tokens.
* **AC-5**: Global command palette (CommandDialog) triggered by keyboard shortcuts (Cmd+K or Ctrl+K) enables fast keyboard navigation across tasks, repositories, and workspace settings, showing recent tasks persisted in client cache.
* **AC-6**: Console application shell (ConsoleLayout) provides a responsive collapsible sidebar navigation with workspace switcher, header bar with breadcrumb trail and connection status pulse, and initial route views for tasks, task details, repositories, and settings.

## Decision

**Chosen option**: Option 1: Tailwind CSS v4 CSS first theme tokens with Radix UI accessible primitives, Class Variance Authority (CVA), `@tanstack/react-virtual`, and Lucide icons.

We adopt Tailwind CSS v4 with native CSS variables in `@theme`, Radix UI headless primitives for complex accessible behaviors, CVA for component variant management, Sonner for notifications, cmdk for the command palette, `@tanstack/react-virtual` with `ansi-to-react` for virtualized streaming logs, and cookie based layout persistence to prevent hydration shift.

**Implementation skills**: `tailwind-design-system` (`wshobson/agents`, `.agents/skills/tailwind-design-system/`) · `nextjs-app-router-patterns` (`wshobson/agents`, `.agents/skills/nextjs-app-router-patterns/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

### Design tokens schema (Tailwind CSS v4 `@theme`)

Tokens are declared in `apps/web/src/app/globals.css` using the CSS first `@theme` directive with OKLCH color coordinates:

```css
@import "tailwindcss";

@theme {
  /* Neutral scale (Zinc based dark palette) */
  --color-background: oklch(14.5% 0.005 285);
  --color-foreground: oklch(98% 0.002 285);

  --color-card: oklch(17% 0.006 285);
  --color-card-foreground: oklch(98% 0.002 285);

  --color-popover: oklch(17% 0.006 285);
  --color-popover-foreground: oklch(98% 0.002 285);

  --color-primary: oklch(98% 0.002 285);
  --color-primary-foreground: oklch(14.5% 0.005 285);

  --color-secondary: oklch(23% 0.008 285);
  --color-secondary-foreground: oklch(98% 0.002 285);

  --color-muted: oklch(23% 0.008 285);
  --color-muted-foreground: oklch(65% 0.01 285);

  --color-accent: oklch(25% 0.01 285);
  --color-accent-foreground: oklch(98% 0.002 285);

  --color-destructive: oklch(55% 0.22 25);
  --color-destructive-foreground: oklch(98% 0.002 285);

  --color-border: oklch(26% 0.008 285);
  --color-input: oklch(26% 0.008 285);
  --color-ring: oklch(65% 0.15 160);

  /* Agent execution status tokens (aligned with database enums) */
  --color-status-queued: oklch(55% 0.01 285);
  --color-status-running: oklch(68% 0.16 240);
  --color-status-waiting: oklch(78% 0.16 75);
  --color-status-succeeded: oklch(72% 0.19 155);
  --color-status-failed: oklch(60% 0.22 25);
  --color-status-cancelled: oklch(45% 0.01 285);

  /* Typography */
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);

  /* Corner radius tokens */
  --radius-sm: 0.25rem;
  --radius-md: 0.375rem;
  --radius-lg: 0.5rem;
  --radius-xl: 0.75rem;
}
```

### Component inventory and architecture

Components live in `apps/web/src/components/ui/` and use React 19 props conventions (direct ref props without forwardRef):

* `Button`: 6 variants (`default`, `secondary`, `destructive`, `outline`, `ghost`, `link`), 4 sizes (`sm`, `default`, `lg`, `icon`), with `asChild` support via Radix Slot.
* `Badge`: status indicators with variants aligned to PostgreSQL database status enums (`default`, `secondary`, `outline`, `destructive`, `queued`, `running`, `awaiting_approval`, `succeeded`, `failed`, `cancelled`), supporting an optional pulsing indicator dot for active tasks.
* `Card`: compound component including `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, and `CardFooter`.
* `Dialog`: accessible modal overlay based on `@radix-ui/react-dialog` with focus trapping, escape key dismiss, and smooth entrance transitions.
* `Tabs`: accessible tab navigation based on `@radix-ui/react-tabs`.
* `Table`: dense data display supporting `TableHeader`, `TableBody`, `TableRow`, `TableHead`, and `TableCell` with sticky header capability.
* `Input` & `Textarea`: accessible form inputs with subtle border styling and glowing focus rings.
* `Select`: accessible dropdown selection based on `@radix-ui/react-select`.
* `Toast`: asynchronous toast notifications using Sonner, configured with dark mode styling and action buttons.
* `CommandDialog`: modal command palette based on `cmdk` for fast keyboard navigation (`Cmd+K`), surfacing static navigation routes and recent tasks cached in `localStorage` under key `aoa_recent_tasks`.
* `TerminalViewer`: virtualized scrolling log container powered by `@tanstack/react-virtual` and `ansi-to-react`. Features ANSI color formatting, clean plain text search and clipboard copy, line numbering, auto scroll pin toggle via `scrollToIndex({ align: 'end' })`, and a 10,000 line ring buffer with `requestAnimationFrame` batching to prevent browser tab memory exhaustion.

### Console layout shell (`apps/web/src/components/layout/`)

The console shell wraps all authenticated routes:
* `Sidebar`: 240px width collapsible panel containing organization logo, organization selector, navigation links (`Tasks`, `Repositories`, `Settings`), active agent run counters, and user profile trigger. Persists collapse state in a cookie (`aoa_sidebar_state`) so server rendering matches client state without hydration shift.
* `Header`: sticky top bar displaying dynamic breadcrumb path via `BreadcrumbContext`, global command palette trigger button, and live connection status pulse (tracking active SSE stream on `/tasks/[id]`, or static engine health on top level views).
* `Main`: scrollable content canvas accommodating data tables or split pane task execution views.

### State transitions

#### TerminalViewer scroll pin state machine
* State 1: `Pinned` (default). New incoming log chunks automatically invoke virtualizer `scrollToIndex({ align: 'end' })`.
* User scrolls up (> 40px from bottom): transition to `Unpinned`. Displays floating button "Scroll to bottom" with unread line count badge.
* User clicks floating button or scrolls to bottom: transition to `Pinned`. Floating button disappears.

#### Sidebar toggle state machine
* Desktop (viewport >= 1024px): `Expanded` by default. Can toggle to `Collapsed` (64px icon only mode) via header button. Preference persists in `aoa_sidebar_state` cookie.
* Mobile or Tablet (viewport < 1024px): `Hidden` by default. Toggles as an overlay drawer via hamburger button.

### Interface surface

| Surface or Route | Kind | Key inputs | Key outputs or views | Auth requirement | Key error states |
|---|---|---|---|---|---|
| `/tasks` | Server Component | `searchParams`: status, page | Paginated tasks table, status filter tabs | Clerk session | Empty task list, database connection failure |
| `/tasks/[id]` | Server Component | `params.id`: UUID | Split view: task run metadata, LangGraph step timeline, live terminal log | Clerk session | 404 task not found, unauthorized tenant access |
| `/repositories` | Server Component | None | Connected GitHub repositories grid, repository metadata | Clerk session | GitHub App installation required |
| `/settings` | Server Component | None | Workspace configuration form, sandbox provider toggle | Clerk org admin | Unauthorized role |
| `TerminalViewer` | Client Component | `logs`: string array, `isStreaming`: boolean | Virtualized ANSI rendered log stream, line numbers | Inherited | Parse error fallback to raw text |
| `CommandDialog` | Client Component | `open`: boolean, `onOpenChange` | Quick search input, filtered command list | Inherited | Empty search results |

### Value sourcing

| Action or View | Value produced or displayed | Source |
|---|---|---|
| Tenant resolution | Organization UUID `org_id` | Helper `getOrgByClerkId(clerkOrgId)` in `apps/web/src/db/` |
| Tasks table list | Task title, repository name, status badge, created timestamp | PostgreSQL `tasks` and `repositories` tables via Drizzle ORM |
| Task status badge | Status color (queued, running, waiting, succeeded, failed, cancelled) | `task_runs.status` enum mapped to semantic status tokens |
| Sidebar active runs | Total number of currently executing tasks | Server query: `SELECT count(*) FROM tasks WHERE status = 'running' AND org_id = :org_id` |
| Live terminal output | ANSI formatted log lines, execution timestamps | Server Sent Events stream payload from FastAPI (`/api/v1/tasks/{id}/events`) |
| SSE connection health | Green pulse ("Connected") or amber pulse ("Reconnecting") | Browser EventSource readyState on `/tasks/[id]`, static engine health on top views |
| Breadcrumb navigation | Current route hierarchy (e.g. Tasks > chore: add linting) | `BreadcrumbContext` updated by child page views and route segments |
| Command palette items | Filtered list of actions and recent tasks | Static navigation routes plus recent tasks from `localStorage` (`aoa_recent_tasks`) |
| User profile badge | User avatar, name, organization slug | Clerk user session object |

### Key invariants

* High contrast accessibility: all text tokens against background tokens guarantee a contrast ratio of at least 4.5:1, fulfilling WCAG AA standards.
* Visible focus rings: interactive elements never suppress outline without replacing it with `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`.
* Zero flash of unstyled theme: root layout sets dark class on html element to prevent bright white flash during server side rendering.
* Terminal streaming performance: terminal log viewer handles up to 10,000 log lines without dropping frame rates below 60fps by rendering visible window lines via `@tanstack/react-virtual`.
* Memory safety: terminal ring buffer caps resident lines at 10,000, shedding oldest lines when agent generates massive log volume.
* Clean clipboard copy: copying from terminal viewer strips ANSI codes, delivering clean plain text to clipboard.
* Keyboard trap prevention: modal dialogs trap focus while open and restore focus to trigger elements upon closing.

### Security model

* Read only data access: front end views read data directly through Drizzle ORM read queries scoped to the internal organization UUID via `getOrgByClerkId(clerkOrgId)`.
* Mutation isolation: mutations (starting tasks, aborting runs, updating settings) trigger typed Server Actions or authenticated FastAPI API calls.
* Sanitized terminal output: ANSI log parser escapes raw HTML to prevent cross site scripting (XSS) from malicious output generated in untrusted sandboxes.

### Configuration required

No new external environment variables are required for this foundational UI layer.

### Critical test scenarios

* Happy path: User opens console, navigates to `/tasks`, clicks a task to view split details, and observes the terminal auto scrolling with incoming simulated logs, verifies **AC-1**, **AC-2**, **AC-3**, **AC-6**.
* Terminal scroll interaction: When logs stream rapidly, user scrolls up, verifying auto scroll disengages, unread counter badge appears, and clicking "Scroll to bottom" re-engages pin, verifies **AC-3**.
* Clipboard copy: User copies log text from terminal viewer, verifying clipboard content contains plain text without raw ANSI escape codes, verifies **AC-3**.
* Keyboard navigation: User presses `Cmd+K` anywhere in console, command palette dialog opens with focus trapped, user types "settings", presses Enter, and navigates to `/settings`, verifies **AC-2**, **AC-5**.
* Component accessibility: Vitest component tests verify Button, Dialog, Input, and Table components render correct ARIA attributes and focus styles, verifies **AC-2**.

## Build plan

The build plan follows the Tracer Bullet approach, establishing the full design token foundation, component primitives, terminal streaming viewer, and console shell in shippable increments:

1. [x] Install UI utility dependencies (`class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`, `@radix-ui/react-slot`, `@radix-ui/react-dialog`, `@radix-ui/react-tabs`, `@radix-ui/react-select`, `cmdk`, `sonner`, `@tanstack/react-virtual`, `ansi-to-react`) and configure Tailwind CSS v4 `@theme` tokens in `apps/web/src/app/globals.css`, satisfies **AC-1**.
2. [x] Create utility helper `cn` in `apps/web/src/lib/utils.ts` and build core accessible CVA primitives (Button, Badge, Card, Input, Select, Tabs, Dialog, Table) in `apps/web/src/components/ui/`, satisfies **AC-2**.
3. [x] Implement high performance streaming `TerminalViewer` component with `@tanstack/react-virtual`, `ansi-to-react`, clean plain text copy, search filter, line numbers, and a 10,000 line ring buffer, satisfies **AC-3**.
4. [x] Configure Sonner toast provider in root layout and implement `CommandDialog` global palette with `Cmd+K` keyboard shortcut listener and local cache for recent tasks, satisfies **AC-4**, **AC-5**.
5. [x] Build console layout shell (`ConsoleLayout`, collapsible `Sidebar` with cookie preference, `Header` with live status indicator and breadcrumb context) and scaffold views for `/tasks`, `/tasks/[id]`, `/repositories`, and `/settings`, satisfies **AC-6**.
6. [x] Implement comprehensive unit and accessibility tests in `apps/web/tests/` using Vitest and React Testing Library, satisfies **AC-2**, **AC-3**, **AC-6**.

## Consequences

**Positive**:
* Cohesive developer tool aesthetic tailored specifically for autonomous agent monitoring and code review.
* High information density without visual clutter, allowing developers to scan multi minute agent runs efficiently.
* WCAG AA accessibility built into base components from day one, preventing expensive retrofits later.
* Direct CSS first Tailwind v4 tokens eliminate Javascript runtime theme overhead and build step bloat.
* Virtualized terminal log viewer handles massive builds and test suites without memory exhaustion or browser tab freezes.
* Reusable component primitives accelerate feature delivery for all subsequent product slices.

**Negative / tradeoffs**:
* Adds Radix UI, TanStack Virtual, and helper dependencies (`cmdk`, `sonner`, `lucide-react`, `cva`, `ansi-to-react`) to `apps/web/package.json`.
* Virtualized terminal log viewer requires maintaining two representations of incoming log lines (ANSI rendered elements and stripped plain text).

**Neutral**:
* Light mode is deferred to a future enhancement, keeping initial token maintenance lean and dark mode focused.

## Follow-up

* [ ] Integrate live EventSource hook in `/tasks/[id]` once the agent engine SSE endpoint is scaffolded in Slice 1.
* [ ] Add monaco editor or lightweight diff viewer component when pull request diff review views are implemented in Slice 2.
