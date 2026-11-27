import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import * as React from "react";
import { BreadcrumbProvider } from "../src/components/layout/breadcrumb-context";
import { TaskDetailClient } from "../src/app/(console)/tasks/[id]/task-detail-client";
import { ORG_FORBIDDEN_EVENT } from "../src/lib/org-recovery";
import { toast } from "../src/components/ui/sonner";

vi.mock("../src/components/ui/sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
  Toaster: () => null,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/tasks/test-task-id",
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

// Mock fetchEventSource from @microsoft/fetch-event-source
let eventSourceCallbacks: {
  onopen?: (res: { ok: boolean; status: number }) => Promise<void>;
  onmessage?: (ev: { id?: string; event?: string; data?: string }) => void;
  onerror?: (err: Error) => void;
  onclose?: () => void;
} = {};
let lastEventSourceHeaders: Record<string, string> | undefined;
let lastEventSourceFetch:
  | ((input: RequestInfo | URL, init?: RequestInit) => Promise<Response>)
  | undefined;

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: vi.fn(async (_url, options) => {
    lastEventSourceHeaders = options.headers;
    lastEventSourceFetch = options.fetch;
    eventSourceCallbacks = {
      onopen: options.onopen,
      onmessage: options.onmessage,
      onerror: options.onerror,
      onclose: options.onclose,
    };
    if (options.onopen) {
      await options.onopen({ ok: true, status: 200 });
    }
  }),
}));

describe("Live Task Streaming and Interactive Collaboration UI", () => {
  const sampleTaskId = "018f6c38-8921-7000-8000-000000000001";

  beforeEach(() => {
    vi.clearAllMocks();
    eventSourceCallbacks = {};
    lastEventSourceHeaders = undefined;
    lastEventSourceFetch = undefined;
    // Mock global fetch for POST endpoints
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (
        url.includes("/intervene") ||
        url.includes("/respond") ||
        url.includes("/abort")
      ) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ status: "ok" }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      });
    });
  });

  it("renders live terminal and developer steering bar", () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    expect(screen.getByText("Live Sandbox Terminal (E2B)")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Send guidance to steer running agent/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Steer Agent/i })
    ).toBeInTheDocument();
  });

  it("sends developer steering guidance when submitted", async () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    const guidanceInput = screen.getByPlaceholderText(
      /Send guidance to steer running agent/i
    );
    fireEvent.change(guidanceInput, {
      target: { value: "Prioritize Clerk JWKS validation" },
    });

    const steerButton = screen.getByRole("button", { name: /Steer Agent/i });
    fireEvent.click(steerButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tasks/${sampleTaskId}/intervene`),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            message: "Prioritize Clerk JWKS validation",
            action_type: "guidance",
          }),
        })
      );
    });

    expect(toast.success).toHaveBeenCalledWith(
      "Guidance sent to running agent."
    );
  });

  it("displays clarification banner and responds when agent triggers human in the loop", async () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    // Simulate incoming task.interrupted SSE event
    expect(eventSourceCallbacks.onmessage).toBeDefined();
    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "100-1",
        event: "task.interrupted",
        data: JSON.stringify({
          prompt: "Which database migration strategy should be used?",
          options: ["Alembic auto-generate", "Manual SQL script"],
          interruption_type: "single_choice",
        }),
      });
    });

    // Clarification card should appear
    await waitFor(() => {
      expect(
        screen.getByText("Clarification Requested by Agent")
      ).toBeInTheDocument();
      expect(
        screen.getByText("Which database migration strategy should be used?")
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Alembic auto-generate" })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Manual SQL script" })
      ).toBeInTheDocument();
    });

    // Select an option and submit
    const optionButton = screen.getByRole("button", {
      name: "Alembic auto-generate",
    });
    fireEvent.click(optionButton);

    const submitButton = screen.getByRole("button", { name: /Submit/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tasks/${sampleTaskId}/respond`),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            response: "Alembic auto-generate",
            selected_option: "Alembic auto-generate",
          }),
        })
      );
    });

    expect(toast.success).toHaveBeenCalledWith(
      "Response submitted. Agent resumed."
    );
  });

  it("sends Clerk Bearer token on SSE stream and intervention requests", async () => {
    const getToken = vi.fn().mockResolvedValue("clerk_jwt_test_token");
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} getToken={getToken} />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(lastEventSourceHeaders?.Authorization).toBe(
        "Bearer clerk_jwt_test_token"
      );
    });

    const guidanceInput = screen.getByPlaceholderText(
      /Send guidance to steer running agent/i
    );
    fireEvent.change(guidanceInput, {
      target: { value: "Verify JWT header" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Steer Agent/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tasks/${sampleTaskId}/intervene`),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: "Bearer clerk_jwt_test_token",
          }),
        })
      );
    });
  });

  it("refreshes Clerk Bearer token on SSE reconnect and preserves Last-Event-ID", async () => {
    const getToken = vi
      .fn()
      .mockResolvedValueOnce("clerk_jwt_initial")
      .mockResolvedValueOnce("clerk_jwt_refreshed");

    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} getToken={getToken} />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(lastEventSourceFetch).toBeDefined();
      expect(lastEventSourceHeaders?.Authorization).toBe(
        "Bearer clerk_jwt_initial"
      );
    });

    // Simulate incoming event with id so Last-Event-ID is tracked
    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "1795646073959-0",
        event: "task.log",
        data: JSON.stringify({ chunk: "line 1\n" }),
      });
    });

    // Simulate initial fetch + subsequent reconnect fetch called by fetchEventSource
    await lastEventSourceFetch!(
      `http://localhost:8000/api/v1/tasks/${sampleTaskId}/events`,
      {
        headers: { ...lastEventSourceHeaders },
      }
    );
    await lastEventSourceFetch!(
      `http://localhost:8000/api/v1/tasks/${sampleTaskId}/events`,
      {
        headers: {
          ...lastEventSourceHeaders,
          "last-event-id": "1795646073959-0",
        },
      }
    );

    const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const reconnectCall = calls[calls.length - 1];
    const reconnectHeaders = reconnectCall[1].headers as Headers;
    expect(reconnectHeaders.get("Authorization")).toBe(
      "Bearer clerk_jwt_refreshed"
    );
    expect(reconnectHeaders.get("Last-Event-ID")).toBe("1795646073959-0");

    // Unexpected close while active triggers retry by throwing; close after terminal status does not
    React.act(() => {
      expect(() => eventSourceCallbacks.onclose?.()).toThrow(
        /Stream closed unexpectedly/
      );
    });
    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "1795646073960-0",
        event: "task.status",
        data: JSON.stringify({ status: "completed" }),
      });
    });
    React.act(() => {
      expect(() => eventSourceCallbacks.onclose?.()).not.toThrow();
    });
  });

  it("streams ANSI log chunks into terminal and syncs step progress across phase tabs", async () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "200-1",
        event: "task.log",
        data: JSON.stringify({
          chunk:
            "\u001b[32m[test]\u001b[0m line A\n\u001b[32m[test]\u001b[0m line B\n",
        }),
      });
      eventSourceCallbacks.onmessage?.({
        id: "200-2",
        event: "task.step",
        data: JSON.stringify({ node: "sandbox_allocate", status: "completed" }),
      });
      eventSourceCallbacks.onmessage?.({
        id: "200-3",
        event: "task.step",
        data: JSON.stringify({ node: "forge_react_loop", status: "running" }),
      });
    });

    expect(screen.getByText(/Showing 30 lines/)).toBeInTheDocument();
    expect(screen.getByText("sandbox_allocate")).toBeInTheDocument();
    expect(screen.getByText("forge_react_loop")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Setup" }));
    expect(screen.getByText("sandbox_allocate")).toBeInTheDocument();
    expect(screen.queryByText("forge_react_loop")).not.toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Loop" }));
    expect(screen.queryByText("sandbox_allocate")).not.toBeInTheDocument();
    expect(screen.getByText("forge_react_loop")).toBeInTheDocument();
  });

  it("handles SSE 401 refresh retry, 403 org recovery dispatch, and 404 error", async () => {
    const getToken = vi.fn().mockResolvedValue("fresh_token");
    const forbiddenSpy = vi.fn();
    window.addEventListener(ORG_FORBIDDEN_EVENT, forbiddenSpy);

    try {
      render(
        <BreadcrumbProvider>
          <TaskDetailClient taskId={sampleTaskId} getToken={getToken} />
        </BreadcrumbProvider>
      );

      await waitFor(() => {
        expect(eventSourceCallbacks.onopen).toBeDefined();
      });

      // First 401 with async token source triggers refresh retry error
      await React.act(async () => {
        await expect(
          eventSourceCallbacks.onopen!({ ok: false, status: 401 })
        ).rejects.toThrow(/Authentication token expired/);
      });

      // Second 401 stops retrying and exposes error message
      await React.act(async () => {
        await eventSourceCallbacks.onopen!({ ok: false, status: 401 });
      });
      expect(
        screen.getByText("Authentication failed: HTTP 401")
      ).toBeInTheDocument();

      // 403 with org_missing payload dispatches org recovery event
      await React.act(async () => {
        await (
          eventSourceCallbacks.onopen as (res: {
            ok: boolean;
            status: number;
            json?: () => Promise<unknown>;
          }) => Promise<void>
        )({
          ok: false,
          status: 403,
          json: async () => ({
            detail: { code: "org_missing", message: "No active organization" },
          }),
        });
      });
      expect(forbiddenSpy).toHaveBeenCalledTimes(1);
      expect(
        screen.getByText("Authentication failed: HTTP 403")
      ).toBeInTheDocument();

      // 404 reports task not found
      await React.act(async () => {
        await eventSourceCallbacks.onopen!({ ok: false, status: 404 });
      });
      expect(
        screen.getByText(`Task ${sampleTaskId} not found`)
      ).toBeInTheDocument();
    } finally {
      window.removeEventListener(ORG_FORBIDDEN_EVENT, forbiddenSpy);
    }
  });

  it("aborts active task, updates status badge to Cancelled, and disables guidance input", async () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    const abortButton = screen.getByRole("button", { name: /Abort Task/i });
    fireEvent.click(abortButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tasks/${sampleTaskId}/abort`),
        expect.objectContaining({ method: "POST" })
      );
      expect(screen.getByText("Cancelled")).toBeInTheDocument();
    });

    expect(toast.error).toHaveBeenCalledWith(
      "Task execution aborted by operator."
    );
    expect(
      screen.queryByRole("button", { name: /Abort Task/i })
    ).not.toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Send guidance to steer running agent/i)
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: /Steer Agent/i })).toBeDisabled();
  });

  it("shows error toasts for failed guidance, empty clarification, and rejected respond", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/intervene")) {
        return Promise.resolve({ ok: false, status: 500 });
      }
      if (url.includes("/respond")) {
        return Promise.resolve({ ok: false, status: 409 });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      });
    });

    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    const guidanceInput = screen.getByPlaceholderText(
      /Send guidance to steer running agent/i
    );
    fireEvent.change(guidanceInput, { target: { value: "Try guidance" } });
    fireEvent.click(screen.getByRole("button", { name: /Steer Agent/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to deliver guidance.");
    });

    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "300-1",
        event: "task.interrupted",
        data: JSON.stringify({
          prompt: "Pick test runner",
          options: ["Vitest", "Jest"],
        }),
      });
    });

    // Empty clarification submission shows validation toast
    fireEvent.click(screen.getByRole("button", { name: /Submit/i }));
    expect(toast.error).toHaveBeenCalledWith(
      "Please enter a response or choose an option."
    );

    // 409 Conflict from /respond keeps banner visible and shows failure toast
    fireEvent.click(screen.getByRole("button", { name: "Vitest" }));
    fireEvent.click(screen.getByRole("button", { name: /Submit/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to submit clarification response."
      );
    });
    expect(
      screen.getByText("Clarification Requested by Agent")
    ).toBeInTheDocument();
  });

  it("hydrates awaiting_input task and completed transcript when orgId is provided", async () => {
    const getToken = vi.fn().mockResolvedValue("org_tok");
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith(`/api/v1/tasks/${sampleTaskId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              title: "Hydrated Task Title",
              repo_full_name: "acme/api",
              branch_name: "feat/streaming",
              status: "awaiting_input",
              interruption_prompt: "Confirm deployment target",
              interruption_type: "clarification",
              interruption_options: ["Staging", "Production"],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      });
    });

    const { unmount } = render(
      <BreadcrumbProvider>
        <TaskDetailClient
          taskId={sampleTaskId}
          orgId="org-uuid-1"
          getToken={getToken}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Hydrated Task Title")).toBeInTheDocument();
      expect(screen.getByText("acme/api")).toBeInTheDocument();
      expect(screen.getByText("feat/streaming")).toBeInTheDocument();
      expect(screen.getByText("Confirm deployment target")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Staging" })
      ).toBeInTheDocument();
    });
    unmount();

    // Completed task hydrates archived transcript
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith(`/api/v1/tasks/${sampleTaskId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              title: "Finished Task",
              repo_full_name: "acme/api",
              branch_name: "main",
              status: "completed",
            }),
        });
      }
      if (url.endsWith(`/api/v1/tasks/${sampleTaskId}/transcript`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              terminal_log: "line 1\nline 2\nline 3\n",
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      });
    });

    render(
      <BreadcrumbProvider>
        <TaskDetailClient
          taskId={sampleTaskId}
          orgId="org-uuid-1"
          getToken={getToken}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Finished Task")).toBeInTheDocument();
      expect(screen.getByText(/Showing 3 lines/)).toBeInTheDocument();
    });
  });

  it("falls back to polling transcript when SSE fails with server error while active", async () => {
    const getToken = vi.fn().mockResolvedValue("poll_tok");
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith(`/api/v1/tasks/${sampleTaskId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              title: "Active Fallback Task",
              status: "in_progress",
            }),
        });
      }
      if (url.endsWith(`/api/v1/tasks/${sampleTaskId}/transcript`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              terminal_log: "polled line 1\npolled line 2\n",
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      });
    });

    render(
      <BreadcrumbProvider>
        <TaskDetailClient
          taskId={sampleTaskId}
          orgId="org-uuid-1"
          getToken={getToken}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(eventSourceCallbacks.onopen).toBeDefined();
    });

    await React.act(async () => {
      await expect(
        eventSourceCallbacks.onopen!({ ok: false, status: 500 })
      ).rejects.toThrow(/HTTP 500/);
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tasks/${sampleTaskId}/transcript`),
        expect.objectContaining({
          headers: { Authorization: "Bearer poll_tok" },
        })
      );
      expect(screen.getByText(/Showing 2 lines/)).toBeInTheDocument();
    });
  });

  it("handles live task.approval_requested, task.budget_updated, and budget_exceeded SSE events (covers: AC-3, AC-5, AC-6)", async () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient
          taskId={sampleTaskId}
          orgId="org-uuid-1"
          isAdmin
          authToken="tok_sse"
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(eventSourceCallbacks.onmessage).toBeDefined();
    });

    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "400-1",
        event: "task.approval_requested",
        data: JSON.stringify({
          approval_id: "app-sse-1",
          risk_category: "destructive_shell",
          action_type: "sandbox_command",
          action_summary: "Execute destructive shell command 'rm -rf /tmp/x'",
          action_payload: { command: "rm -rf /tmp/x" },
          expires_at: "2026-11-27T12:00:00Z",
        }),
      });
      eventSourceCallbacks.onmessage?.({
        id: "400-2",
        event: "task.budget_updated",
        data: JSON.stringify({
          task_cost_cents: 240,
          max_task_cost_cents: 500,
          tokens_used: 9500,
          org_month_cost_cents: 1240,
          max_monthly_org_cost_cents: 10000,
        }),
      });
    });

    expect(screen.getByText("Guardrail Approval Required")).toBeInTheDocument();
    expect(screen.getByText("destructive_shell")).toBeInTheDocument();
    expect(screen.getByText("$2.40 / $5.00")).toBeInTheDocument();
    expect(screen.getByText(/9,500 tokens/i)).toBeInTheDocument();

    await React.act(async () => {
      eventSourceCallbacks.onmessage?.({
        id: "400-3",
        event: "task.status",
        data: JSON.stringify({
          status: "failed",
          failure_reason: "budget_exceeded",
        }),
      });
    });

    expect(
      screen.queryByText("Guardrail Approval Required")
    ).not.toBeInTheDocument();
    expect(screen.getByText("Halted: budget_exceeded")).toBeInTheDocument();
  });

  it("handles approval rejection and 403 org_admin_required on decideApproval (covers: AC-4, AC-7)", async () => {
    const forbiddenEvents: CustomEvent[] = [];
    const listener = (ev: Event) => forbiddenEvents.push(ev as CustomEvent);
    window.addEventListener(ORG_FORBIDDEN_EVENT, listener);

    global.fetch = vi
      .fn()
      .mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith(`/api/v1/tasks/${sampleTaskId}`) && !init?.method) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                title: "Approval Reject Test",
                status: "awaiting_input",
                interruption_prompt: "Approve force push?",
                interruption_type: "approval",
                pending_approval: {
                  approval_id: "app-rej-1",
                  risk_category: "force_git_op",
                  action_type: "sandbox_command",
                  action_summary: "Execute git operation 'git push --force'",
                  action_payload: { command: "git push --force" },
                  expires_at: "2026-11-27T12:00:00Z",
                },
                budget_summary: {
                  task_cost_cents: 10,
                  max_task_cost_cents: 500,
                  tokens_used: 300,
                },
              }),
              { status: 200 }
            )
          );
        }
        if (url.endsWith("/approvals/app-rej-1/decision")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                detail: {
                  code: "org_admin_required",
                  message: "Organization admin role (org:admin) is required",
                },
              }),
              { status: 403 }
            )
          );
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      });

    try {
      render(
        <BreadcrumbProvider>
          <TaskDetailClient
            taskId={sampleTaskId}
            orgId="org-uuid-1"
            isAdmin
            authToken="tok_member"
          />
        </BreadcrumbProvider>
      );

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Reject Action/i })
        ).toBeInTheDocument();
      });

      fireEvent.change(screen.getByLabelText("Approval decision note"), {
        target: { value: "Too risky" },
      });
      fireEvent.click(screen.getByRole("button", { name: /Reject Action/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(
          "Organization admin role (org:admin) is required"
        );
      });
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/approvals/app-rej-1/decision"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ decision: "rejected", note: "Too risky" }),
        })
      );
      expect(forbiddenEvents).toHaveLength(0);
    } finally {
      window.removeEventListener(ORG_FORBIDDEN_EVENT, listener);
    }
  });
});
