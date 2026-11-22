"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Terminal,
  FolderGit2,
  Settings,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const SIDEBAR_COOKIE = "aoa_sidebar_state";

export interface SidebarProps {
  activeRunCount?: number;
  initialCollapsed?: boolean;
}

export function Sidebar({
  activeRunCount = 0,
  initialCollapsed = false,
}: SidebarProps) {
  const pathname = usePathname();
  const isCookieCollapsed = React.useSyncExternalStore(
    () => () => {},
    () => {
      const match = document.cookie.match(/aoa_sidebar_state=([^;]+)/);
      return match ? match[1] === "collapsed" : initialCollapsed;
    },
    () => initialCollapsed
  );
  const [userCollapsed, setUserCollapsed] = React.useState<boolean | null>(
    null
  );
  const isCollapsed =
    userCollapsed !== null ? userCollapsed : isCookieCollapsed;

  const toggleCollapse = () => {
    const nextState = !isCollapsed;
    setUserCollapsed(nextState);
    document.cookie = `${SIDEBAR_COOKIE}=${nextState ? "collapsed" : "expanded"}; path=/; max-age=31536000; SameSite=Lax`;
  };

  const navItems = [
    {
      label: "Tasks",
      href: "/tasks",
      icon: Terminal,
      badge: activeRunCount > 0 ? activeRunCount : undefined,
    },
    {
      label: "Repositories",
      href: "/repositories",
      icon: FolderGit2,
    },
    {
      label: "Settings",
      href: "/settings",
      icon: Settings,
    },
  ];

  return (
    <aside
      className={cn(
        "relative flex flex-col border-r border-border bg-card/60 backdrop-blur transition-all duration-300 z-30 select-none",
        isCollapsed ? "w-16" : "w-60"
      )}
    >
      {/* Brand Header */}
      <div className="flex h-14 items-center justify-between border-b border-border px-3.5">
        <Link
          href="/tasks"
          className={cn(
            "flex items-center gap-2.5 transition-opacity hover:opacity-85",
            isCollapsed && "justify-center w-full"
          )}
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-mono font-bold text-sm shrink-0">
            AoA
          </div>
          {!isCollapsed && (
            <div className="flex flex-col">
              <span className="font-semibold text-sm tracking-tight text-foreground leading-none">
                agentsOnAir
              </span>
              <span className="text-[10px] text-muted-foreground font-mono mt-0.5">
                console v0.1.0
              </span>
            </div>
          )}
        </Link>
      </div>

      {/* Navigation links */}
      <nav className="flex-1 space-y-1 p-2">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors relative",
                isActive
                  ? "bg-accent text-accent-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                isCollapsed && "justify-center px-0 py-2.5"
              )}
              title={isCollapsed ? item.label : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!isCollapsed && (
                <span className="flex-1 truncate">{item.label}</span>
              )}
              {!isCollapsed && item.badge !== undefined && (
                <span className="flex items-center gap-1 text-[11px] font-mono px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-400 font-semibold">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  {item.badge}
                </span>
              )}
              {isCollapsed && item.badge !== undefined && (
                <span className="absolute top-1 right-2 h-2 w-2 rounded-full bg-emerald-400" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Platform Status indicator */}
      {!isCollapsed && (
        <div className="mx-3 mb-2 rounded-lg border border-border bg-zinc-900/40 p-2.5 space-y-1 text-xs">
          <div className="flex items-center justify-between text-[11px] font-medium text-foreground">
            <span className="flex items-center gap-1.5">
              <Bot className="h-3.5 w-3.5 text-emerald-400" />
              Engine
            </span>
            <span className="flex items-center gap-1 text-emerald-400 font-mono text-[10px]">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Online
            </span>
          </div>
          <div className="text-[10px] text-muted-foreground leading-tight">
            E2B sandboxes ready with Docker fallback
          </div>
        </div>
      )}

      {/* Sidebar footer and collapse toggle */}
      <div className="border-t border-border p-2 flex items-center justify-between">
        {!isCollapsed && (
          <div className="flex items-center gap-2 pl-2">
            <ShieldCheck className="h-4 w-4 text-zinc-500" />
            <span className="text-[11px] text-muted-foreground font-mono">
              WCAG AA
            </span>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleCollapse}
          className={cn(
            "h-7 w-7 text-muted-foreground hover:text-foreground",
            isCollapsed && "mx-auto"
          )}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>
    </aside>
  );
}
