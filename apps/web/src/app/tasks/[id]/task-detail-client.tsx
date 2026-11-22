"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  GitBranch,
  FolderGit2,
  Cpu,
  Clock,
  Layers,
  Square,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { TerminalViewer } from "@/components/ui/terminal-viewer";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";
import { toast } from "@/components/ui/sonner";

const mockLogLines = [
  "\u001b[32m[sandbox:init]\u001b[0m Provisioning E2B Firecracker microVM (uuid: vm_01j982a)...",
  "\u001b[32m[sandbox:ready]\u001b[0m Hardware microVM allocated in 420ms with 4 vCPU, 8GB RAM.",
  "\u001b[34m[git:clone]\u001b[0m Cloning repository agentsOnAir/core (ref: refs/heads/feat/clerk-auth)...",
  "\u001b[34m[git:clone]\u001b[0m Cloned 1,482 objects in 1.1s.",
  "\u001b[35m[agent:planner]\u001b[0m Autonomous engineer initialized with model: gemini-1.5-pro.",
  "\u001b[35m[agent:planner]\u001b[0m Plan formulated:",
  "  1. Locate authentication dependency in apps/agent/app/dependencies.py",
  "  2. Add Clerk JWKS URL fetch and public key validation logic",
  "  3. Inject HTTPBearer dependency on protected endpoints",
  "  4. Run pytest test suite inside sandbox to verify rejection of invalid JWTs",
  "\u001b[33m[tool:bash]\u001b[0m $ uv pip list | grep -i jwt",
  "PyJWT==2.8.0",
  "cryptography==42.0.5",
  "\u001b[33m[tool:edit]\u001b[0m Modified apps/agent/app/dependencies.py (+48 lines, -12 lines)",
  "\u001b[33m[tool:bash]\u001b[0m $ pytest tests/test_auth.py -v",
  "============================= test session starts ==============================",
  "platform linux -- Python 3.12.2, pytest-8.1.1",
  "collected 4 items",
  "",
  "tests/test_auth.py::test_missing_bearer_header PASSED                    [ 25%]",
  "tests/test_auth.py::test_expired_clerk_jwt_rejected PASSED               [ 50%]",
  "tests/test_auth.py::test_invalid_audience_rejected PASSED                [ 75%]",
  "tests/test_auth.py::test_valid_clerk_jwt_accepted PASSED                 [100%]",
  "",
  "\u001b[32m============================== 4 passed in 1.84s ===============================\u001b[0m",
  "\u001b[35m[agent:reviewer]\u001b[0m Initiating independent code review on git diff...",
  "\u001b[32m[agent:reviewer]\u001b[0m Diff verified clean. Zero security findings. All tests passing.",
  "\u001b[32m[task:complete]\u001b[0m Verified pull request ready for publication.",
];

export function TaskDetailClient({ taskId }: { taskId: string }) {
  useBreadcrumbs([
    { label: "Tasks", href: "/tasks" },
    { label: taskId.slice(0, 8) },
  ]);

  const handleAbort = () => {
    toast.error("Task execution aborted by operator.");
  };

  return (
    <div className="space-y-6">
      {/* Top Navigation & Actions Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="icon" className="h-8 w-8">
            <Link href="/tasks">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <Badge variant="running" pulse>
                Running
              </Badge>
              <span className="font-mono text-xs text-muted-foreground">
                {taskId}
              </span>
            </div>
            <h1 className="text-lg font-bold tracking-tight text-foreground mt-1">
              feat(auth): integrate Clerk JWKS JWT verification in FastAPI
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleAbort}
            className="gap-1.5 text-rose-400 border-rose-500/30 hover:bg-rose-500/10"
          >
            <Square className="h-3.5 w-3.5" />
            <span>Abort Task</span>
          </Button>
        </div>
      </div>

      {/* Split Pane: Metadata on Left, Terminal on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Pane: Metadata and Execution Steps */}
        <div className="lg:col-span-4 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">
                Task Metadata
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <FolderGit2 className="h-3.5 w-3.5 text-blue-400" />
                  Repository
                </span>
                <span className="font-mono font-medium text-foreground">
                  agentsOnAir/core
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <GitBranch className="h-3.5 w-3.5 text-zinc-400" />
                  Branch
                </span>
                <span className="font-mono font-medium text-foreground">
                  feat/clerk-auth
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <Cpu className="h-3.5 w-3.5 text-emerald-400" />
                  Sandbox
                </span>
                <span className="font-mono font-medium text-emerald-400">
                  E2B (vm_01j982a)
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5 text-zinc-400" />
                  Elapsed
                </span>
                <span className="font-mono text-foreground">2m 14s</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <Layers className="h-3.5 w-3.5 text-purple-400" />
                  Agent Model
                </span>
                <span className="font-mono text-foreground">
                  gemini-1.5-pro
                </span>
              </div>
            </CardContent>
          </Card>

          {/* LangGraph Steps Timeline */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">
                LangGraph Node Steps
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="relative pl-6 space-y-4 border-l-2 border-border ml-2 text-xs">
                <div className="relative">
                  <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-zinc-950 font-bold text-[10px]">
                    ✓
                  </span>
                  <div className="font-medium text-foreground">
                    sandbox_allocate
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    E2B microVM allocated
                  </div>
                </div>

                <div className="relative">
                  <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-zinc-950 font-bold text-[10px]">
                    ✓
                  </span>
                  <div className="font-medium text-foreground">
                    repo_checkout
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    Clean working tree cloned
                  </div>
                </div>

                <div className="relative">
                  <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-zinc-950 font-bold text-[10px]">
                    ✓
                  </span>
                  <div className="font-medium text-foreground">
                    agent_execute
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    Code edited & tests passing
                  </div>
                </div>

                <div className="relative">
                  <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-400 animate-pulse text-zinc-950 font-bold text-[10px]">
                    ●
                  </span>
                  <div className="font-medium text-emerald-400">
                    code_review
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    Independent reviewer checking diff
                  </div>
                </div>

                <div className="relative opacity-40">
                  <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-zinc-700 text-zinc-400 text-[10px]">
                    ○
                  </span>
                  <div className="font-medium text-foreground">
                    github_pr_open
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    Publish verified PR
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right Pane: Live Streaming Terminal Log Viewer */}
        <div className="lg:col-span-8 h-[640px]">
          <TerminalViewer
            logs={mockLogLines}
            isStreaming
            title="Live Sandbox Terminal (E2B)"
            className="h-full"
          />
        </div>
      </div>
    </div>
  );
}
