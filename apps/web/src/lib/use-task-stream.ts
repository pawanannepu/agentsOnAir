import * as React from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import {
  dispatchOrgForbiddenEvent,
  extractOrgForbiddenDetail,
} from "@/lib/org-recovery";

export interface StepEvent {
  node: string;
  status: "pending" | "running" | "completed" | "failed";
  timestamp?: string;
  payload?: Record<string, unknown>;
}

export interface InterruptionState {
  prompt: string;
  options?: string[];
  interruptionType?: string;
  expiresAt?: string | null;
}

export interface PendingApprovalState {
  approvalId: string;
  riskCategory: string;
  actionType: string;
  actionSummary: string;
  actionPayload: Record<string, unknown>;
  expiresAt: string;
}

export interface BudgetSummaryState {
  taskCostCents: number;
  maxTaskCostCents: number;
  tokensUsed: number;
  orgMonthCostCents?: number;
  maxMonthlyOrgCostCents?: number;
  partialDiff?: string | null;
}

export interface UseTaskStreamOptions {
  taskId: string;
  orgId?: string;
  initialLogs?: string[];
  initialStatus?: string;
  autoConnect?: boolean;
  apiBaseUrl?: string;
  getToken?: () => Promise<string | null>;
  authToken?: string;
}

export interface UseTaskStreamReturn {
  logs: string[];
  steps: StepEvent[];
  interruption: InterruptionState | null;
  pendingApproval: PendingApprovalState | null;
  budgetSummary: BudgetSummaryState | null;
  failureReason: string | null;
  status: string;
  isStreaming: boolean;
  error: string | null;
  hydrateSnapshot: (snapshot: {
    status?: string;
    interruption?: InterruptionState | null;
    pendingApproval?: PendingApprovalState | null;
    budgetSummary?: BudgetSummaryState | null;
    failureReason?: string | null;
    logs?: string[];
    replaceLogs?: boolean;
  }) => void;
  intervene: (message: string, actionType?: string) => Promise<boolean>;
  respond: (response: string, selectedOption?: string) => Promise<boolean>;
  decideApproval: (
    approvalId: string,
    decision: "approved" | "rejected",
    note?: string
  ) => Promise<{ ok: boolean; error?: string }>;
  abort: (reason?: string) => Promise<boolean>;
  connect: () => void;
  disconnect: () => void;
}

const MAX_LOG_LINES = 5000;

declare global {
  interface Window {
    Clerk?: {
      session?: {
        getToken?: () => Promise<string | null>;
      };
    };
  }
}

async function resolveBearerToken(
  getToken?: () => Promise<string | null>,
  authToken?: string
): Promise<string | null> {
  if (getToken) {
    try {
      const t = await getToken();
      if (t) return t;
    } catch {
      // Fallback to authToken or window.Clerk
    }
  }
  if (authToken) {
    return authToken;
  }
  if (typeof window !== "undefined" && window.Clerk?.session?.getToken) {
    try {
      return await window.Clerk.session.getToken();
    } catch {
      return null;
    }
  }
  return null;
}

export function useTaskStream({
  taskId,
  orgId: _orgId,
  initialLogs = [],
  initialStatus = "running",
  autoConnect = true,
  apiBaseUrl,
  getToken,
  authToken,
}: UseTaskStreamOptions): UseTaskStreamReturn {
  void _orgId;
  const [logs, setLogs] = React.useState<string[]>(initialLogs);
  const [steps, setSteps] = React.useState<StepEvent[]>([]);
  const [interruption, setInterruption] =
    React.useState<InterruptionState | null>(null);
  const [pendingApproval, setPendingApproval] =
    React.useState<PendingApprovalState | null>(null);
  const [budgetSummary, setBudgetSummary] =
    React.useState<BudgetSummaryState | null>(null);
  const [failureReason, setFailureReason] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<string>(initialStatus);
  const [isStreaming, setIsStreaming] = React.useState<boolean>(false);
  const [error, setError] = React.useState<string | null>(null);

  const [enabled, setEnabled] = React.useState<boolean>(autoConnect);
  const lastEventIdRef = React.useRef<string | null>(null);

  const baseUrl =
    apiBaseUrl ||
    process.env.NEXT_PUBLIC_AGENT_API_URL ||
    "http://localhost:8000";

  const connect = React.useCallback(() => {
    setEnabled(true);
  }, []);

  const disconnect = React.useCallback(() => {
    setEnabled(false);
    setIsStreaming(false);
  }, []);

  const hydrateSnapshot = React.useCallback(
    (snapshot: {
      status?: string;
      interruption?: InterruptionState | null;
      pendingApproval?: PendingApprovalState | null;
      budgetSummary?: BudgetSummaryState | null;
      failureReason?: string | null;
      logs?: string[];
      replaceLogs?: boolean;
    }) => {
      if (snapshot.status) {
        setStatus(snapshot.status);
      }
      if (snapshot.interruption !== undefined) {
        setInterruption(snapshot.interruption);
      }
      if (snapshot.pendingApproval !== undefined) {
        setPendingApproval(snapshot.pendingApproval);
      }
      if (snapshot.budgetSummary !== undefined) {
        setBudgetSummary(snapshot.budgetSummary);
      }
      if (snapshot.failureReason !== undefined) {
        setFailureReason(snapshot.failureReason);
      }
      if (snapshot.logs && snapshot.logs.length > 0) {
        setLogs((prev) =>
          snapshot.replaceLogs || prev.length === 0 ? snapshot.logs! : prev
        );
      }
    },
    []
  );

  React.useEffect(() => {
    if (!enabled || !taskId) {
      return;
    }

    const controller = new AbortController();
    const streamUrl = `${baseUrl}/api/v1/tasks/${taskId}/events`;
    let cancelled = false;
    const hasAsyncTokenSource =
      Boolean(getToken) ||
      (typeof window !== "undefined" &&
        Boolean(window.Clerk?.session?.getToken));

    const openStream = (initialToken: string | null) => {
      if (cancelled || controller.signal.aborted) {
        return;
      }

      let pendingInitialToken: string | null | undefined = initialToken;
      let terminalStatusReached = false;
      let authRetryCount = 0;

      void fetchEventSource(streamUrl, {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "text/event-stream",
          ...(initialToken ? { Authorization: `Bearer ${initialToken}` } : {}),
          ...(lastEventIdRef.current
            ? { "Last-Event-ID": lastEventIdRef.current }
            : {}),
        },
        fetch: async (input, init) => {
          const freshToken =
            pendingInitialToken !== undefined
              ? pendingInitialToken
              : await resolveBearerToken(getToken, authToken);
          pendingInitialToken = undefined;

          const headers = new Headers(init?.headers);
          if (freshToken) {
            headers.set("Authorization", `Bearer ${freshToken}`);
          } else {
            headers.delete("Authorization");
          }
          if (lastEventIdRef.current && !headers.has("Last-Event-ID")) {
            headers.set("Last-Event-ID", lastEventIdRef.current);
          }

          return globalThis.fetch(input, {
            ...init,
            headers,
          });
        },
        signal: controller.signal,
        async onopen(response) {
          if (response.ok && response.status === 200) {
            authRetryCount = 0;
            setIsStreaming(true);
            setError(null);
            return;
          }
          if (response.status === 401) {
            if (hasAsyncTokenSource && authRetryCount < 1) {
              authRetryCount += 1;
              setIsStreaming(false);
              throw new Error("Authentication token expired; refreshing");
            }
            setError(`Authentication failed: HTTP ${response.status}`);
            controller.abort();
            setIsStreaming(false);
            return;
          }
          if (response.status === 403) {
            if (typeof response.json === "function") {
              try {
                const payload = (await response.json()) as unknown;
                const detail = extractOrgForbiddenDetail(payload);
                if (detail) {
                  dispatchOrgForbiddenEvent(detail);
                }
              } catch {
                // Ignore non-JSON 403 body
              }
            }
            setError(`Authentication failed: HTTP ${response.status}`);
            controller.abort();
            setIsStreaming(false);
            return;
          }
          if (response.status === 404) {
            setError(`Task ${taskId} not found`);
            controller.abort();
            setIsStreaming(false);
            return;
          }
          setIsStreaming(false);
          const errMessage = `Failed to connect: HTTP ${response.status}`;
          setError(errMessage);
          throw new Error(errMessage);
        },
        onmessage(ev) {
          if (ev.id) {
            lastEventIdRef.current = ev.id;
          }

          if (!ev.data) {
            return;
          }

          try {
            const parsed = JSON.parse(ev.data) as Record<string, unknown>;

            if (ev.event === "task.log") {
              const chunk =
                typeof parsed.chunk === "string" ? parsed.chunk : "";
              if (chunk) {
                const rawLines = chunk.split("\n");
                const newLines =
                  rawLines.length > 1 && rawLines[rawLines.length - 1] === ""
                    ? rawLines.slice(0, -1)
                    : rawLines;

                setLogs((prev) => {
                  const combined = [...prev, ...newLines];
                  return combined.length > MAX_LOG_LINES
                    ? combined.slice(-MAX_LOG_LINES)
                    : combined;
                });
              }
            } else if (ev.event === "task.step") {
              const node = typeof parsed.node === "string" ? parsed.node : "";
              const stepStatus =
                parsed.status === "completed" ||
                parsed.status === "running" ||
                parsed.status === "failed"
                  ? parsed.status
                  : "pending";

              if (node) {
                setSteps((prev) => {
                  const existingIndex = prev.findIndex((s) => s.node === node);
                  const updatedStep: StepEvent = {
                    node,
                    status: stepStatus,
                    timestamp:
                      typeof parsed.timestamp === "string"
                        ? parsed.timestamp
                        : undefined,
                    payload: parsed,
                  };

                  if (existingIndex >= 0) {
                    const copy = [...prev];
                    copy[existingIndex] = updatedStep;
                    return copy;
                  }
                  return [...prev, updatedStep];
                });
              }
            } else if (ev.event === "task.approval_requested") {
              const approvalId =
                typeof parsed.approval_id === "string"
                  ? parsed.approval_id
                  : "";
              const riskCategory =
                typeof parsed.risk_category === "string"
                  ? parsed.risk_category
                  : "destructive_shell";
              const actionType =
                typeof parsed.action_type === "string"
                  ? parsed.action_type
                  : "sandbox_command";
              const actionSummary =
                typeof parsed.action_summary === "string"
                  ? parsed.action_summary
                  : "Approval required";
              const actionPayload =
                parsed.action_payload &&
                typeof parsed.action_payload === "object"
                  ? (parsed.action_payload as Record<string, unknown>)
                  : {};
              const expiresAt =
                typeof parsed.expires_at === "string" ? parsed.expires_at : "";

              if (approvalId) {
                setPendingApproval({
                  approvalId,
                  riskCategory,
                  actionType,
                  actionSummary,
                  actionPayload,
                  expiresAt,
                });
              }
              setInterruption({
                prompt: actionSummary,
                options: ["Approve", "Reject"],
                interruptionType: "approval",
                expiresAt,
              });
              setStatus("awaiting_input");
            } else if (ev.event === "task.budget_updated") {
              setBudgetSummary((prev) => ({
                taskCostCents:
                  typeof parsed.task_cost_cents === "number"
                    ? parsed.task_cost_cents
                    : (prev?.taskCostCents ?? 0),
                maxTaskCostCents:
                  typeof parsed.max_task_cost_cents === "number"
                    ? parsed.max_task_cost_cents
                    : (prev?.maxTaskCostCents ?? 500),
                tokensUsed:
                  typeof parsed.tokens_used === "number"
                    ? parsed.tokens_used
                    : (prev?.tokensUsed ?? 0),
                orgMonthCostCents:
                  typeof parsed.org_month_cost_cents === "number"
                    ? parsed.org_month_cost_cents
                    : prev?.orgMonthCostCents,
                maxMonthlyOrgCostCents:
                  typeof parsed.max_monthly_org_cost_cents === "number"
                    ? parsed.max_monthly_org_cost_cents
                    : prev?.maxMonthlyOrgCostCents,
                partialDiff: prev?.partialDiff ?? null,
              }));
            } else if (ev.event === "task.interrupted") {
              const prompt =
                typeof parsed.prompt === "string"
                  ? parsed.prompt
                  : "Human clarification needed";
              const options = Array.isArray(parsed.options)
                ? (parsed.options.filter(
                    (o) => typeof o === "string"
                  ) as string[])
                : undefined;
              const interruptionType =
                typeof parsed.interruption_type === "string"
                  ? parsed.interruption_type
                  : undefined;
              const expiresAt =
                typeof parsed.expires_at === "string"
                  ? parsed.expires_at
                  : undefined;

              setInterruption({
                prompt,
                options,
                interruptionType,
                expiresAt,
              });
              setStatus("awaiting_input");
            } else if (ev.event === "task.resumed") {
              setInterruption(null);
              setPendingApproval(null);
              setStatus("in_progress");
            } else if (ev.event === "task.status") {
              const nextStatus =
                typeof parsed.status === "string" ? parsed.status : "";
              const nextReason =
                typeof parsed.failure_reason === "string"
                  ? parsed.failure_reason
                  : typeof parsed.reason === "string"
                    ? parsed.reason
                    : null;
              if (nextReason) {
                setFailureReason(nextReason);
              }
              if (nextStatus) {
                setStatus(nextStatus);
                if (
                  nextStatus === "completed" ||
                  nextStatus === "failed" ||
                  nextStatus === "cancelled"
                ) {
                  setPendingApproval(null);
                  setInterruption(null);
                  terminalStatusReached = true;
                  setIsStreaming(false);
                }
              }
            }
          } catch {
            // Non JSON payload, ignore
          }
        },
        onclose() {
          setIsStreaming(false);
          if (!terminalStatusReached && !controller.signal.aborted) {
            throw new Error("Stream closed unexpectedly; reconnecting");
          }
        },
        onerror(err) {
          setIsStreaming(false);
          if (!controller.signal.aborted) {
            setError(
              err instanceof Error ? err.message : "Stream connection error"
            );
          }
        },
      });
    };

    if (!hasAsyncTokenSource) {
      openStream(authToken ?? null);
    } else {
      void resolveBearerToken(getToken, authToken).then(openStream);
    }

    return () => {
      cancelled = true;
      controller.abort();
      setIsStreaming(false);
    };
  }, [authToken, baseUrl, enabled, getToken, taskId]);

  const intervene = React.useCallback(
    async (message: string, actionType = "guidance"): Promise<boolean> => {
      try {
        const token = await resolveBearerToken(getToken, authToken);
        const res = await fetch(`${baseUrl}/api/v1/tasks/${taskId}/intervene`, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ message, action_type: actionType }),
        });
        if (res.status === 403 && typeof res.json === "function") {
          try {
            const detail = extractOrgForbiddenDetail(await res.json());
            if (detail) dispatchOrgForbiddenEvent(detail);
          } catch {
            // Ignore
          }
        }
        return res.ok;
      } catch {
        return false;
      }
    },
    [authToken, baseUrl, getToken, taskId]
  );

  const respond = React.useCallback(
    async (response: string, selectedOption?: string): Promise<boolean> => {
      try {
        const token = await resolveBearerToken(getToken, authToken);
        const res = await fetch(`${baseUrl}/api/v1/tasks/${taskId}/respond`, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            response,
            selected_option: selectedOption,
          }),
        });
        if (res.status === 403 && typeof res.json === "function") {
          try {
            const detail = extractOrgForbiddenDetail(await res.json());
            if (detail) dispatchOrgForbiddenEvent(detail);
          } catch {
            // Ignore
          }
        }
        if (res.ok) {
          setInterruption(null);
          setStatus("in_progress");
          return true;
        }
        return false;
      } catch {
        return false;
      }
    },
    [authToken, baseUrl, getToken, taskId]
  );

  const decideApproval = React.useCallback(
    async (
      approvalId: string,
      decision: "approved" | "rejected",
      note?: string
    ): Promise<{ ok: boolean; error?: string }> => {
      try {
        const token = await resolveBearerToken(getToken, authToken);
        const res = await fetch(
          `${baseUrl}/api/v1/tasks/${taskId}/approvals/${approvalId}/decision`,
          {
            method: "POST",
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({
              decision,
              note: note?.trim() || undefined,
            }),
          }
        );
        if (res.status === 403 && typeof res.json === "function") {
          const payload = (await res.json().catch(() => null)) as {
            detail?: { code?: string; message?: string } | string;
          } | null;
          const detail = extractOrgForbiddenDetail(payload);
          if (detail) dispatchOrgForbiddenEvent(detail);
          const msg =
            typeof payload?.detail === "object" && payload?.detail?.message
              ? payload.detail.message
              : "Organization admin role (org:admin) is required.";
          return { ok: false, error: msg };
        }
        if (!res.ok) {
          const payload = (await res.json().catch(() => null)) as {
            detail?: string;
          } | null;
          return {
            ok: false,
            error: payload?.detail || `Request failed (${res.status})`,
          };
        }

        setPendingApproval(null);
        setInterruption(null);
        setStatus(decision === "approved" ? "in_progress" : "failed");
        if (decision === "rejected") {
          setFailureReason("approval_rejected");
        }
        return { ok: true };
      } catch {
        return { ok: false, error: "Unable to reach agent engine." };
      }
    },
    [authToken, baseUrl, getToken, taskId]
  );

  const abort = React.useCallback(
    async (reason = "Operator cancelled execution"): Promise<boolean> => {
      try {
        const token = await resolveBearerToken(getToken, authToken);
        const res = await fetch(`${baseUrl}/api/v1/tasks/${taskId}/abort`, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ reason }),
        });
        if (res.status === 403 && typeof res.json === "function") {
          try {
            const detail = extractOrgForbiddenDetail(await res.json());
            if (detail) dispatchOrgForbiddenEvent(detail);
          } catch {
            // Ignore
          }
        }
        if (res.ok) {
          setStatus("cancelled");
          setIsStreaming(false);
          return true;
        }
        return false;
      } catch {
        return false;
      }
    },
    [authToken, baseUrl, getToken, taskId]
  );

  return {
    logs,
    steps,
    interruption,
    pendingApproval,
    budgetSummary,
    failureReason,
    status,
    isStreaming,
    error,
    hydrateSnapshot,
    intervene,
    respond,
    decideApproval,
    abort,
    connect,
    disconnect,
  };
}
