"use client";

import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { useRouter } from "next/navigation";
import {
  Search,
  Terminal,
  FolderGit2,
  Settings,
  PlusCircle,
  FileCode2,
  GitPullRequest,
  BarChart3,
} from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "./dialog";

export interface CommandDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface RecentTask {
  id: string;
  title: string;
  repo: string;
}

const RECENT_TASKS_KEY = "aoa_recent_tasks";

export function CommandDialog({ open, onOpenChange }: CommandDialogProps) {
  const router = useRouter();

  // Lazy initializer avoids setState within useEffect
  const [recentTasks] = React.useState<RecentTask[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = localStorage.getItem(RECENT_TASKS_KEY);
      return stored ? JSON.parse(stored).slice(0, 5) : [];
    } catch {
      return [];
    }
  });

  // Global keyboard shortcut Cmd+K or Ctrl+K
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onOpenChange]);

  const runCommand = React.useCallback(
    (command: () => void) => {
      onOpenChange(false);
      command();
    },
    [onOpenChange]
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 shadow-2xl border-border bg-card max-w-xl">
        <DialogTitle className="sr-only">Command Palette</DialogTitle>
        <CommandPrimitive className="flex h-full w-full flex-col overflow-hidden rounded-xl bg-card text-card-foreground">
          <div className="flex items-center border-b border-border px-3">
            <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
            <CommandPrimitive.Input
              placeholder="Type a command or search tasks..."
              className="flex h-11 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>

          <CommandPrimitive.List className="max-h-[300px] overflow-y-auto overflow-x-hidden p-2 text-xs">
            <CommandPrimitive.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results found.
            </CommandPrimitive.Empty>

            {/* Quick Navigation Group */}
            <CommandPrimitive.Group
              heading="Navigation"
              className="text-muted-foreground px-2 py-1.5 font-semibold text-[11px]"
            >
              <CommandPrimitive.Item
                onSelect={() => runCommand(() => router.push("/tasks"))}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <Terminal className="h-4 w-4 text-emerald-400" />
                <span>All Tasks</span>
              </CommandPrimitive.Item>
              <CommandPrimitive.Item
                onSelect={() => runCommand(() => router.push("/reviews"))}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <GitPullRequest className="h-4 w-4 text-purple-400" />
                <span>Pull Request Reviews</span>
              </CommandPrimitive.Item>
              <CommandPrimitive.Item
                onSelect={() => runCommand(() => router.push("/analytics"))}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <BarChart3 className="h-4 w-4 text-sky-400" />
                <span>Quality & Turnaround Analytics</span>
              </CommandPrimitive.Item>
              <CommandPrimitive.Item
                onSelect={() => runCommand(() => router.push("/repositories"))}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <FolderGit2 className="h-4 w-4 text-blue-400" />
                <span>Connected Repositories</span>
              </CommandPrimitive.Item>
              <CommandPrimitive.Item
                onSelect={() => runCommand(() => router.push("/settings"))}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <Settings className="h-4 w-4 text-zinc-400" />
                <span>Workspace Settings</span>
              </CommandPrimitive.Item>
            </CommandPrimitive.Group>

            {/* Actions Group */}
            <CommandPrimitive.Group
              heading="Actions"
              className="text-muted-foreground px-2 py-1.5 font-semibold text-[11px] mt-2 border-t border-border pt-2"
            >
              <CommandPrimitive.Item
                onSelect={() =>
                  runCommand(() => {
                    router.push("/tasks");
                  })
                }
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <PlusCircle className="h-4 w-4 text-emerald-400" />
                <span>Create New Task</span>
              </CommandPrimitive.Item>
            </CommandPrimitive.Group>

            {/* Recent Tasks */}
            {recentTasks.length > 0 && (
              <CommandPrimitive.Group
                heading="Recent Tasks"
                className="text-muted-foreground px-2 py-1.5 font-semibold text-[11px] mt-2 border-t border-border pt-2"
              >
                {recentTasks.map((task) => (
                  <CommandPrimitive.Item
                    key={task.id}
                    onSelect={() =>
                      runCommand(() => router.push(`/tasks/${task.id}`))
                    }
                    className="flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
                  >
                    <div className="flex items-center gap-2 truncate">
                      <FileCode2 className="h-4 w-4 text-zinc-400 shrink-0" />
                      <span className="truncate">{task.title}</span>
                    </div>
                    <span className="text-[11px] text-muted-foreground shrink-0 font-mono">
                      {task.repo}
                    </span>
                  </CommandPrimitive.Item>
                ))}
              </CommandPrimitive.Group>
            )}
          </CommandPrimitive.List>

          <div className="flex items-center justify-between border-t border-border px-3 py-2 text-[11px] text-muted-foreground bg-muted/30">
            <span>Use arrow keys to navigate, enter to select</span>
            <kbd className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              ESC
            </kbd>
          </div>
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  );
}
