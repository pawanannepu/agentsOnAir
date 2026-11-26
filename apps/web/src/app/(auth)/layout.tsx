import * as React from "react";
import Link from "next/link";
import { ShieldCheck, Terminal } from "lucide-react";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative min-h-screen flex flex-col bg-background text-foreground antialiased font-sans overflow-hidden">
      {/* Subtle zinc/emerald ambient grid backdrop */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,oklch(25%_0.04_160_/_0.18),transparent_55%)]"
      />

      {/* Minimal branded auth header without Sidebar */}
      <header className="relative z-10 flex h-14 items-center justify-between border-b border-border/70 bg-card/40 backdrop-blur px-6">
        <Link
          href="/sign-in"
          className="flex items-center gap-2.5 transition-opacity hover:opacity-85"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-mono font-bold text-sm">
            AoA
          </div>
          <div className="flex flex-col">
            <span className="font-semibold text-sm tracking-tight text-foreground leading-none">
              agentsOnAir
            </span>
            <span className="text-[10px] text-muted-foreground font-mono mt-0.5">
              autonomous engineering console
            </span>
          </div>
        </Link>

        <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
          <Terminal className="h-3.5 w-3.5 text-emerald-400" />
          <span className="hidden sm:inline">Isolated Sandbox Execution</span>
        </div>
      </header>

      {/* Centered auth flow container */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 py-10">
        <div className="w-full max-w-md flex flex-col items-center">
          {children}
        </div>
      </main>

      {/* Trust & compliance footer */}
      <footer className="relative z-10 border-t border-border/60 bg-card/30 px-6 py-3 flex items-center justify-between text-[11px] text-muted-foreground font-mono">
        <span className="flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
          Tenant isolated workspaces · Immutable audit trail
        </span>
        <span className="hidden sm:inline">E2B Firecracker microVMs</span>
      </footer>
    </div>
  );
}
