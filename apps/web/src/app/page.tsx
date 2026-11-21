export default function HomePage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center font-mono font-bold text-emerald-400 text-sm">
            AoA
          </div>
          <span className="font-semibold text-lg tracking-tight">agentsOnAir</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
            v0.1.0 scaffold
          </span>
        </div>
        <div className="flex items-center gap-4 text-sm text-zinc-400">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
            Monorepo online
          </span>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto p-8 space-y-8">
        <section className="space-y-3">
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Autonomous Engineer and Reviewer Platform
          </h1>
          <p className="text-zinc-400 text-base max-w-2xl leading-relaxed">
            Develops, tests, and verifies code inside isolated sandboxes before opening pull requests. Monorepo foundation initialized with Next.js web console and Python FastAPI agent engine.
          </p>
        </section>

        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-white">Web Console</h2>
              <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono">apps/web</span>
            </div>
            <p className="text-sm text-zinc-400">
              Next.js 16 App Router with React 19, TypeScript, and Tailwind CSS.
            </p>
            <div className="text-xs font-mono text-emerald-400 pt-2 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
              Ready on port 3000
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-white">Agent Engine</h2>
              <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono">apps/agent</span>
            </div>
            <p className="text-sm text-zinc-400">
              Python 3.12+ FastAPI service powered by uv for async loops and tool execution.
            </p>
            <div className="text-xs font-mono text-emerald-400 pt-2 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
              Ready on port 8000 (/api/v1/health)
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-white">Local Services</h2>
              <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono">docker-compose.yml</span>
            </div>
            <p className="text-sm text-zinc-400">
              PostgreSQL 16 persistence and Redis 7 task queue broker for ARQ workers.
            </p>
            <div className="text-xs font-mono text-zinc-400 pt-2">
              docker compose up -d
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-white">Execution Isolation</h2>
              <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono">SandboxProvider</span>
            </div>
            <p className="text-sm text-zinc-400">
              Hardware microVMs (E2B) in cloud staging and production with local Docker fallback.
            </p>
            <div className="text-xs font-mono text-zinc-400 pt-2">
              SANDBOX_PROVIDER=docker
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-zinc-800/80 px-8 py-4 text-xs text-zinc-500 flex justify-between">
        <span>agentsOnAir · Monorepo Foundation</span>
        <span>Turborepo · Next.js · FastAPI · uv</span>
      </footer>
    </div>
  );
}
