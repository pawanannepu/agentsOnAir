"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBreadcrumbs } from "./breadcrumb-context";

export interface HeaderProps {
  onOpenCommand: () => void;
  isStreamActive?: boolean;
}

export function Header({ onOpenCommand, isStreamActive = false }: HeaderProps) {
  const { breadcrumbs } = useBreadcrumbs();

  return (
    <header className="sticky top-0 z-20 flex h-14 w-full items-center justify-between border-b border-border bg-card/60 backdrop-blur px-6">
      {/* Breadcrumb path */}
      <nav
        aria-label="Breadcrumb"
        className="flex items-center gap-1.5 text-xs text-muted-foreground font-medium"
      >
        <Link href="/tasks" className="hover:text-foreground transition-colors">
          Console
        </Link>
        {breadcrumbs.map((crumb, idx) => (
          <React.Fragment key={crumb.label + idx}>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
            {crumb.href ? (
              <Link
                href={crumb.href}
                className="hover:text-foreground transition-colors max-w-[200px] truncate"
              >
                {crumb.label}
              </Link>
            ) : (
              <span className="text-foreground font-semibold max-w-[240px] truncate">
                {crumb.label}
              </span>
            )}
          </React.Fragment>
        ))}
      </nav>

      {/* Right actions: search command trigger and connection pulse */}
      <div className="flex items-center gap-3">
        {/* Command palette search trigger */}
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenCommand}
          className="h-8 gap-2 px-3 text-xs text-muted-foreground hover:text-foreground border-border bg-muted/30"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Search...</span>
          <kbd className="pointer-events-none hidden sm:inline-flex h-4 select-none items-center gap-0.5 rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
            <span className="text-xs">⌘</span>K
          </kbd>
        </Button>

        {/* Live SSE status indicator */}
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-zinc-900/40 px-2.5 py-1 text-[11px] font-mono text-muted-foreground">
          {isStreamActive ? (
            <>
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"></span>
              </span>
              <span className="text-emerald-400">Live SSE</span>
            </>
          ) : (
            <>
              <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
              <span className="text-zinc-400">FastAPI Online</span>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
