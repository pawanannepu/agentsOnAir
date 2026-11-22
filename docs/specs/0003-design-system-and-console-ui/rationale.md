# Rationale: 0003. Design system and console UI foundation

## Context

The agentsOnAir platform empowers developers to launch autonomous coding agents and automated code reviews that run inside isolated microVM sandboxes. The web console serves as the mission control center where developers monitor task progress, read streaming sandbox terminal logs, answer agent clarification prompts, inspect proposed code diffs, and configure repository guardrails.

Developer tools demand a distinct user interface profile compared to consumer applications. They require high information density, deep contrast with dark mode by default, unambiguous execution state indicators, and keyboard first navigation. When an autonomous agent runs a complex build or test suite inside a sandbox, terminal output can stream thousands of lines in seconds. If the front end component layer is unoptimized or holds an unbounded array in memory, log bursts freeze the browser tab, trigger garbage collection pauses, and degrade the developer experience.

Additionally, modern accessibility is a strict requirement under the project conventions (WCAG AA). Rebuilding interactive primitives such as modal dialogs, accessible dropdown selects, and focus trapped palettes from scratch often leads to subtle accessibility bugs, keyboard navigation failures, and inconsistent focus outlines. Layout preferences such as sidebar collapse state must persist across sessions without introducing hydration mismatches or layout shifts during server rendering.

Finally, the web console operates on Next.js 16 App Router with React 19 and Tailwind CSS v4. The styling architecture must align with Tailwind CSS v4 CSS first `@theme` directives, avoiding deprecated JavaScript configuration patterns or heavy runtime styling engines that conflict with React Server Components.

## Options considered

### Option 1: Tailwind CSS v4 with Radix UI Primitives, Class Variance Authority (CVA), TanStack Virtual, and Lucide Icons (Chosen)

This option uses Tailwind CSS v4 native CSS variables defined inside the `@theme` directive, combined with Radix UI unstyled accessible primitives for complex interactive components (Dialog, Tabs, Select, Slot). Component styling is encapsulated using Class Variance Authority (CVA) alongside `clsx` and `tailwind-merge` for clean variant authoring. Specialized developer components complete the foundation:
* Sonner for toast notifications.
* cmdk for the global command palette.
* `@tanstack/react-virtual` for 60fps virtualized terminal streaming with a 10,000 line ring buffer.
* `ansi-to-react` for rendering ANSI terminal colors with sanitized plain text extraction for search and copy actions.
* Cookie based sidebar persistence to eliminate hydration shifts between server and client.

**Pros**:
* Full accessibility baseline (WCAG AA) out of the box with tested keyboard navigation and focus management.
* Zero runtime styling overhead; all utility classes compile directly into CSS at build time.
* Total visual freedom; components are styled entirely with project tokens rather than overriding vendor CSS.
* Virtualized terminal log viewer handles massive builds and test suites without memory exhaustion or browser tab freezes.
* Clean separation of concerns with React Server Components by default and client directives isolated to interactive primitives.
* Industry standard pattern with extensive community documentation and proven developer ergonomics.

**Cons**:
* Requires installing headless Radix packages, TanStack Virtual, and helper libraries in `apps/web/package.json`.
* Requires maintaining component files locally in `src/components/ui/` rather than consuming a single monolithic npm package.

### Option 2: Pre-packaged Component Library (Mantine, Chakra UI, or Ant Design)

This option adopts a comprehensive third party component library offering ready made buttons, dialogs, tables, and form inputs with built in theme providers.

**Pros**:
* Fast initial scaffolding with hundreds of ready made components available immediately.
* Single vendor dependency for all UI building blocks.

**Cons**:
* Runtime CSS in JS architecture conflicts with React Server Components and introduces client side bundle bloat.
* Bypasses Tailwind CSS v4 utility classes and creates dual styling paradigms across the web console.
* Overriding vendor styling to match dark developer tool aesthetics requires extensive CSS specificity hacks.
* Does not solve streaming log virtualization or command palette integration without secondary packages.

### Option 3: Custom Headless Primitives with Plain HTML5 and ARIA

This option builds all interactive elements using standard HTML5 elements (dialog, button, table) styled with Tailwind CSS v4, avoiding external component dependencies.

**Pros**:
* Zero external UI dependencies, minimizing package installation size and dependency maintenance.
* Complete ownership of every line of component code.

**Cons**:
* High engineering cost to manually implement robust focus trapping, keyboard navigation, and screen reader announcements.
* Significant risk of accessibility regressions across browsers and assistive devices.
* Slower velocity for subsequent product slices that require rich interactive controls.

## Rationale

We choose Option 1 because it delivers the optimal balance between high velocity, complete visual control, robust performance, and uncompromised accessibility.

Autonomous agent development requires specialized UI components that generic component libraries do not provide well, notably streaming terminal viewers, live graph step visualizers, and dense status tables. By pairing Tailwind CSS v4 CSS first theme tokens with Radix UI headless primitives, we gain the rock solid accessibility guarantees of Radix without inheriting opinions on styling, layout, or design aesthetics.

For streaming terminal output, adopting `@tanstack/react-virtual` solves a critical operational bottleneck. Autonomous coding runs can emit tens of thousands of lines during package installations, builds, and test runs. Rendering unbounded DOM nodes or relying on basic unvirtualized containers causes severe DOM bloat and tab crashes. `@tanstack/react-virtual` renders only the lines visible in the container viewport, enabling smooth 60fps scrolling even when the resident ring buffer holds 10,000 lines. Pairing it with `ansi-to-react` ensures accurate color reproduction while maintaining an unformatted plain text copy buffer for developer ergonomics.

Tailwind CSS v4 introduces a streamlined CSS first engine. Declaring our semantic tokens directly in `src/app/globals.css` with `@theme` eliminates the legacy JavaScript configuration file and ensures that tokens map directly to native CSS custom properties. This pattern allows both Server Components and Client Components to consume tokens consistently without hydration mismatches or client runtime overhead.

Class Variance Authority (CVA) provides a structured, declarative way to author component variants (such as button sizes, badge execution states aligned with database enums, and card styles) while maintaining full TypeScript type safety. Integrating Sonner and cmdk gives our console immediate parity with modern developer tools like Linear and GitHub, offering rapid keyboard navigation and fluid asynchronous notifications.
