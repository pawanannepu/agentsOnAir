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
  Send,
  HelpCircle,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TerminalViewer } from "@/components/ui/terminal-viewer";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";
import { toast } from "@/components/ui/sonner";
import {
  dispatchOrgForbiddenEvent,
  extractOrgForbiddenDetail,
} from "@/lib/org-recovery";
import { useTaskStream, type StepEvent } from "@/lib/use-task-stream";

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

const defaultWorkflowSteps: StepEvent[] = [
  { node: "sandbox_allocate", status: "completed" },
  { node: "repo_checkout", status: "completed" },
  { node: "agent_execute", status: "completed" },
  { node: "code_review", status: "running" },
  { node: "github_pr_open", status: "pending" },
];

export interface TaskDetailClientProps {
  taskId: string;
  orgId?: string;
  authToken?: string;
  getToken?: () => Promise<string | null>;
}

export function TaskDetailClient({
  taskId,
  orgId,
  authToken,
  getToken,
}: TaskDetailClientProps) {
  useBreadcrumbs([
    { label: "Tasks", href: "/tasks" },
    { label: taskId.slice(0, 8) },
  ]);

  const {
    logs,
    steps,
    interruption,
    status,
    isStreaming,
    error,
    hydrateSnapshot,
    intervene,
    respond,
    abort,
  } = useTaskStream({
    taskId,
    orgId,
    authToken,
    getToken,
    initialLogs: orgId ? [] : mockLogLines,
    initialStatus: orgId ? "queued" : "running",
  });

  const [guidanceText, setGuidanceText] = React.useState("");
  const [isSubmittingGuidance, setIsSubmittingGuidance] = React.useState(false);

  const [clarificationResponse, setClarificationResponse] = React.useState("");
  const [selectedOption, setSelectedOption] = React.useState<string | null>(
    null
  );
  const [isResponding, setIsResponding] = React.useState(false);
  const [isAborting, setIsAborting] = React.useState(false);
  const [phaseTab, setPhaseTab] = React.useState<"all" | "setup" | "execution">(
    "all"
  );
  const [taskMeta, setTaskMeta] = React.useState<{
    title: string;
    repo: string;
    branch: string;
  }>({
    title: "feat(auth): integrate Clerk JWKS JWT verification in FastAPI",
    repo: "agentsOnAir/core",
    branch: "feat/clerk-auth",
  });

  React.useEffect(() => {
    if (!orgId || !taskId) {
      return;
    }
    let active = true;
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    const loadTask = async () => {
      try {
        const token = getToken
          ? await getToken()
          : authToken ||
            (typeof window !== "undefined" && window.Clerk?.session?.getToken
              ? await window.Clerk.session.getToken()
              : null);
        const res = await fetch(`${baseUrl}/api/v1/tasks/${taskId}`, {
          credentials: "include",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (res.status === 403 && active) {
          const detail = extractOrgForbiddenDetail(
            await res.json().catch(() => null)
          );
          if (detail) {
            dispatchOrgForbiddenEvent(detail);
          }
          return;
        }
        if (!res.ok || !active) {
          return;
        }
        const data = (await res.json()) as {
          title?: string;
          repo_full_name?: string;
          branch_name?: string;
          status?: string;
          interruption_prompt?: string | null;
          interruption_type?: string | null;
          interruption_options?: string[] | null;
          interruption_expires_at?: string | null;
        };
        if (!active) {
          return;
        }
        if (data.title) {
          setTaskMeta({
            title: data.title,
            repo: data.repo_full_name || "agentsOnAir/core",
            branch: data.branch_name || "main",
          });
        }

        const hydratedInterruption =
          data.status === "awaiting_input" && data.interruption_prompt
            ? {
                prompt: data.interruption_prompt,
                options: Array.isArray(data.interruption_options)
                  ? data.interruption_options
                  : undefined,
                interruptionType: data.interruption_type ?? undefined,
                expiresAt: data.interruption_expires_at ?? undefined,
              }
            : null;

        let transcriptLines: string[] | undefined;
        if (
          data.status &&
          ["completed", "failed", "cancelled"].includes(data.status)
        ) {
          const transcriptRes = await fetch(
            `${baseUrl}/api/v1/tasks/${taskId}/transcript`,
            {
              credentials: "include",
              headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            }
          );
          if (transcriptRes.ok && active) {
            const transcriptData = (await transcriptRes.json()) as {
              terminal_log?: string;
            };
            if (transcriptData.terminal_log) {
              const rawLines = transcriptData.terminal_log.split("\n");
              transcriptLines =
                rawLines.length > 1 && rawLines[rawLines.length - 1] === ""
                  ? rawLines.slice(0, -1)
                  : rawLines;
            }
          }
        }

        if (active) {
          hydrateSnapshot({
            status: data.status,
            interruption: hydratedInterruption,
            logs: transcriptLines,
          });
        }
      } catch {
        // Keep initial fallback metadata
      }
    };

    void loadTask();
    return () => {
      active = false;
    };
  }, [authToken, getToken, hydrateSnapshot, orgId, taskId]);

  // Restricted network fallback: poll /transcript when SSE errors out
  React.useEffect(() => {
    if (
      !orgId ||
      !taskId ||
      isStreaming ||
      !error ||
      error.startsWith("Authentication failed") ||
      ["completed", "failed", "cancelled"].includes(status)
    ) {
      return;
    }

    let active = true;
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    const pollTranscript = async () => {
      try {
        const token = getToken
          ? await getToken()
          : authToken ||
            (typeof window !== "undefined" && window.Clerk?.session?.getToken
              ? await window.Clerk.session.getToken()
              : null);
        const res = await fetch(
          `${baseUrl}/api/v1/tasks/${taskId}/transcript`,
          {
            credentials: "include",
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          }
        );
        if (res.status === 403 && active) {
          const detail = extractOrgForbiddenDetail(
            await res.json().catch(() => null)
          );
          if (detail) {
            dispatchOrgForbiddenEvent(detail);
          }
          return;
        }
        if (!res.ok || !active) return;
        const data = (await res.json()) as { terminal_log?: string };
        if (data.terminal_log && active) {
          const rawLines = data.terminal_log.split("\n");
          const lines =
            rawLines.length > 1 && rawLines[rawLines.length - 1] === ""
              ? rawLines.slice(0, -1)
              : rawLines;
          hydrateSnapshot({ logs: lines, replaceLogs: true });
        }
      } catch {
        // Ignore transient polling failures
      }
    };

    void pollTranscript();
    const timer = setInterval(() => void pollTranscript(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [
    authToken,
    error,
    getToken,
    hydrateSnapshot,
    isStreaming,
    orgId,
    status,
    taskId,
  ]);

  const handleAbort = () => {
    toast.error("Task execution aborted by operator.");
    setIsAborting(true);
    void abort("Aborted by console operator").finally(() => {
      setIsAborting(false);
    });
  };

  const handleSendGuidance = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = guidanceText.trim();
    if (!text) {
      return;
    }

    setIsSubmittingGuidance(true);
    const success = await intervene(text, "guidance");
    setIsSubmittingGuidance(false);

    if (success) {
      toast.success("Guidance sent to running agent.");
      setGuidanceText("");
    } else {
      toast.error("Failed to deliver guidance.");
    }
  };

  const handleRespondClarification = async (e?: React.FormEvent) => {
    if (e) {
      e.preventDefault();
    }
    const responsePayload =
      clarificationResponse.trim() || selectedOption || "";
    if (!responsePayload) {
      toast.error("Please enter a response or choose an option.");
      return;
    }

    setIsResponding(true);
    const success = await respond(responsePayload, selectedOption || undefined);
    setIsResponding(false);

    if (success) {
      toast.success("Response submitted. Agent resumed.");
      setClarificationResponse("");
      setSelectedOption(null);
    } else {
      toast.error("Failed to submit clarification response.");
    }
  };

  const displaySteps = steps.length > 0 ? steps : defaultWorkflowSteps;
  const filteredSteps = React.useMemo(() => {
    if (phaseTab === "all") return displaySteps;
    if (phaseTab === "setup") {
      return displaySteps.filter((s) =>
        ["sandbox_allocate", "repo_checkout", "baseline_testing"].includes(
          s.node
        )
      );
    }
    return displaySteps.filter(
      (s) =>
        !["sandbox_allocate", "repo_checkout", "baseline_testing"].includes(
          s.node
        )
    );
  }, [displaySteps, phaseTab]);

  const renderBadge = () => {
    if (status === "awaiting_input" || interruption) {
      return (
        <Badge variant="waiting" pulse>
          Awaiting Clarification
        </Badge>
      );
    }
    if (status === "completed" || status === "succeeded") {
      return <Badge variant="succeeded">Completed</Badge>;
    }
    if (status === "cancelled") {
      return <Badge variant="cancelled">Cancelled</Badge>;
    }
    if (status === "failed") {
      return <Badge variant="failed">Failed</Badge>;
    }
    return (
      <Badge variant="running" pulse>
        Running
      </Badge>
    );
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
              {renderBadge()}
              <span className="font-mono text-xs text-muted-foreground">
                {taskId}
              </span>
            </div>
            <h1 className="text-lg font-bold tracking-tight text-foreground mt-1">
              {taskMeta.title}
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status !== "cancelled" &&
            status !== "completed" &&
            status !== "failed" && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleAbort}
                disabled={isAborting}
                className="gap-1.5 text-rose-400 border-rose-500/30 hover:bg-rose-500/10"
              >
                {isAborting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Square className="h-3.5 w-3.5" />
                )}
                <span>Abort Task</span>
              </Button>
            )}
        </div>
      </div>

      {/* Human in the loop Clarification Banner */}
      {interruption && (
        <Card className="border-amber-500/40 bg-amber-500/10 shadow-lg">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2 text-amber-400">
              <HelpCircle className="h-5 w-5" />
              <CardTitle className="text-sm font-semibold">
                Clarification Requested by Agent
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-foreground font-medium">
              {interruption.prompt}
            </p>

            {interruption.options && interruption.options.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {interruption.options.map((option) => (
                  <Button
                    key={option}
                    type="button"
                    variant={selectedOption === option ? "default" : "outline"}
                    size="sm"
                    onClick={() => {
                      setSelectedOption(option);
                      setClarificationResponse(option);
                    }}
                    className={
                      selectedOption === option
                        ? "bg-amber-500 text-zinc-950 font-medium hover:bg-amber-400"
                        : "border-amber-500/30 text-amber-200 hover:bg-amber-500/20"
                    }
                  >
                    {option}
                  </Button>
                ))}
              </div>
            )}

            <form
              onSubmit={handleRespondClarification}
              className="flex items-center gap-2 pt-2"
            >
              <Input
                value={clarificationResponse}
                onChange={(e) => setClarificationResponse(e.target.value)}
                placeholder="Type your clarification or choice..."
                className="bg-background/80 border-amber-500/30 text-xs"
              />
              <Button
                type="submit"
                size="sm"
                disabled={isResponding}
                className="bg-amber-500 text-zinc-950 hover:bg-amber-400 font-medium gap-1.5"
              >
                {isResponding ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                <span>Submit</span>
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Split Pane: Metadata & Steps on Left, Terminal & Guidance on Right */}
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
                  {taskMeta.repo}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <GitBranch className="h-3.5 w-3.5 text-zinc-400" />
                  Branch
                </span>
                <span className="font-mono font-medium text-foreground">
                  {taskMeta.branch}
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
            <CardHeader className="pb-3 space-y-2">
              <CardTitle className="text-sm font-semibold">
                LangGraph Node Steps
              </CardTitle>
              <Tabs
                value={phaseTab}
                onValueChange={(v) =>
                  setPhaseTab(v as "all" | "setup" | "execution")
                }
              >
                <TabsList className="h-7 bg-muted/60">
                  <TabsTrigger value="all" className="text-[11px] px-2 py-0.5">
                    All
                  </TabsTrigger>
                  <TabsTrigger
                    value="setup"
                    className="text-[11px] px-2 py-0.5"
                  >
                    Setup
                  </TabsTrigger>
                  <TabsTrigger
                    value="execution"
                    className="text-[11px] px-2 py-0.5"
                  >
                    Loop
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </CardHeader>
            <CardContent>
              <div className="relative pl-6 space-y-4 border-l-2 border-border ml-2 text-xs">
                {filteredSteps.map((step) => {
                  const isDone = step.status === "completed";
                  const isRunning = step.status === "running";
                  const isFailed = step.status === "failed";

                  return (
                    <div key={step.node} className="relative">
                      {isDone && (
                        <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-zinc-950 font-bold text-[10px]">
                          ✓
                        </span>
                      )}
                      {isRunning && (
                        <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-400 animate-pulse text-zinc-950 font-bold text-[10px]">
                          ●
                        </span>
                      )}
                      {isFailed && (
                        <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-zinc-950 font-bold text-[10px]">
                          ✕
                        </span>
                      )}
                      {!isDone && !isRunning && !isFailed && (
                        <span className="absolute -left-[31px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-zinc-800 text-zinc-400 text-[10px]">
                          ○
                        </span>
                      )}
                      <div
                        className={
                          isRunning
                            ? "font-medium text-emerald-400"
                            : isFailed
                              ? "font-medium text-rose-400"
                              : "font-medium text-foreground"
                        }
                      >
                        {step.node}
                      </div>
                      <div className="text-[11px] text-muted-foreground capitalize">
                        {step.status}
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right Pane: Live Streaming Terminal & Developer Steering */}
        <div className="lg:col-span-8 space-y-3">
          <div className="h-[580px]">
            <TerminalViewer
              logs={logs}
              isStreaming={isStreaming}
              title="Live Sandbox Terminal (E2B)"
              className="h-full"
            />
          </div>

          {/* Developer Steering Guidance Input Bar */}
          <form
            onSubmit={handleSendGuidance}
            className="flex items-center gap-2 bg-card border border-border p-2 rounded-lg shadow-sm"
          >
            <Input
              value={guidanceText}
              onChange={(e) => setGuidanceText(e.target.value)}
              placeholder="Send guidance to steer running agent (e.g. 'Use uv instead of pip', 'Prioritize auth check')..."
              disabled={
                isSubmittingGuidance ||
                status === "completed" ||
                status === "cancelled"
              }
              className="text-xs border-0 focus-visible:ring-1"
            />
            <Button
              type="submit"
              size="sm"
              disabled={
                !guidanceText.trim() ||
                isSubmittingGuidance ||
                status === "completed" ||
                status === "cancelled"
              }
              className="gap-1.5 shrink-0"
            >
              {isSubmittingGuidance ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              <span>Steer Agent</span>
            </Button>
          </form>

          {error && (
            <div className="flex items-center gap-2 text-xs text-rose-400 px-2">
              <AlertCircle className="h-3.5 w-3.5" />
              <span>{error}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
