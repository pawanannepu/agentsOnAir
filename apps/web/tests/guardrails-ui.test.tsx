import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import * as React from "react";
import {
  SettingsUnauthorizedView,
  SettingsView,
} from "../src/app/(console)/settings/settings-view";
import { RepositoriesView } from "../src/app/(console)/repositories/repositories-view";
import { TaskDetailClient } from "../src/app/(console)/tasks/[id]/task-detail-client";
import { BreadcrumbProvider } from "../src/components/layout/breadcrumb-context";
import { toast } from "../src/components/ui/sonner";

vi.mock("../src/components/ui/sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
  Toaster: () => null,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: vi.fn().mockResolvedValue(undefined),
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  window.Element.prototype.scrollIntoView = vi.fn();
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("Guardrails & Budgets Console UI (AC-7)", () => {
  it("renders SettingsView monthly usage bar and submits guardrail budgets", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/v1/organizations/settings") && !init?.method) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: "org_1",
                settings: { sandbox_provider: "e2b", timeout_minutes: 12 },
              }),
              { status: 200 }
            )
          );
        }
        if (url.endsWith("/api/v1/organizations/guardrails")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                protected_branches: ["main", "release/*"],
                protected_branch_guard: true,
                require_approval_for: [
                  "destructive_shell",
                  "sensitive_path_edit",
                ],
                max_task_cost_cents: 600,
                max_monthly_org_cost_cents: 12000,
                timeout_minutes: 12,
                max_cycles: 4,
                network_egress_mode: "off_after_install",
                allowed_egress_domains: [],
                large_diff_lines_threshold: 400,
              }),
              { status: 200 }
            )
          );
        }
        if (url.endsWith("/api/v1/organizations/usage")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                billing_month: "2026-11",
                total_tokens: 45000,
                total_cost_cents: 1250,
                max_monthly_org_cost_cents: 12000,
                remaining_cents: 10750,
              }),
              { status: 200 }
            )
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify({ id: "org_1", settings: {} }), {
            status: 200,
          })
        );
      });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BreadcrumbProvider>
        <SettingsView canPersistToApi getToken={async () => "fake_jwt_token"} />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(
        screen.getByText(/\$12\.50 spent of \$120\.00 cap/i)
      ).toBeInTheDocument();
    });

    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/organizations/settings"),
        expect.objectContaining({ method: "PATCH" })
      );
    });
  });

  it("renders RepositoriesView from API and opens Guardrail Overrides drawer", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/api/v1/repositories")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [
                {
                  id: "repo-1",
                  name: "payments",
                  full_name: "acme/payments",
                  default_branch: "main",
                  is_private: true,
                  effective_policy: {
                    protected_branches: ["main"],
                    protected_branch_guard: true,
                    require_approval_for: ["destructive_shell"],
                    max_task_cost_cents: 500,
                    max_monthly_org_cost_cents: 10000,
                    timeout_minutes: 10,
                    max_cycles: 3,
                    network_egress_mode: "off_after_install",
                    allowed_egress_domains: [],
                    large_diff_lines_threshold: 500,
                  },
                },
              ],
              total: 1,
            }),
            { status: 200 }
          )
        );
      }
      if (url.endsWith("/api/v1/repositories/repo-1/guardrails")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              repo_id: "repo-1",
              org_defaults: {
                protected_branches: ["main", "master"],
                protected_branch_guard: true,
                require_approval_for: ["destructive_shell"],
                max_task_cost_cents: 500,
                max_monthly_org_cost_cents: 10000,
                timeout_minutes: 10,
                max_cycles: 3,
                network_egress_mode: "off_after_install",
                allowed_egress_domains: [],
                large_diff_lines_threshold: 500,
              },
              repo_overrides: { max_task_cost_cents: 250 },
              effective_policy: {
                protected_branches: ["main", "master"],
                protected_branch_guard: true,
                require_approval_for: ["destructive_shell"],
                max_task_cost_cents: 250,
                max_monthly_org_cost_cents: 10000,
                timeout_minutes: 10,
                max_cycles: 3,
                network_egress_mode: "off_after_install",
                allowed_egress_domains: [],
                large_diff_lines_threshold: 500,
              },
            }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BreadcrumbProvider>
        <RepositoriesView
          canLoadFromApi
          isAdmin
          getToken={async () => "fake_jwt_token"}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("payments")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Guardrails/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/Guardrail Overrides · acme\/payments/i)
      ).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("250")).toBeInTheDocument();
  });

  it("renders live cost meter and org:admin Approval Gate card in TaskDetailClient", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/v1/tasks/task-1") && !init?.method) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: "task-1",
                title: "Update workflow",
                repo_full_name: "acme/payments",
                branch_name: "feat/ci",
                status: "awaiting_input",
                interruption_prompt:
                  "Write to sensitive path '.github/workflows/ci.yml'",
                interruption_type: "approval",
                pending_approval: {
                  approval_id: "app-1",
                  risk_category: "sensitive_path_edit",
                  action_type: "sandbox_file_write",
                  action_summary:
                    "Write to sensitive path '.github/workflows/ci.yml'",
                  action_payload: { path: ".github/workflows/ci.yml" },
                  expires_at: "2026-11-26T22:00:00Z",
                },
                budget_summary: {
                  task_cost_cents: 125,
                  max_task_cost_cents: 500,
                  tokens_used: 4200,
                  partial_diff: null,
                },
              }),
              { status: 200 }
            )
          );
        }
        if (url.endsWith("/approvals/app-1/decision")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                approval_id: "app-1",
                status: "approved",
                task_status: "in_progress",
              }),
              { status: 200 }
            )
          );
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BreadcrumbProvider>
        <TaskDetailClient
          taskId="task-1"
          orgId="org-1"
          isAdmin
          getToken={async () => "fake_jwt_token"}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(
        screen.getByText("Guardrail Approval Required")
      ).toBeInTheDocument();
    });
    expect(screen.getByText("$1.25 / $5.00")).toBeInTheDocument();
    expect(screen.getByText("sensitive_path_edit")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Approve Action/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(
          "/api/v1/tasks/task-1/approvals/app-1/decision"
        ),
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("renders SettingsUnauthorizedView for non-admins and handles save errors (covers: AC-1, AC-7)", async () => {
    const { unmount } = render(
      <BreadcrumbProvider>
        <SettingsUnauthorizedView />
      </BreadcrumbProvider>
    );
    expect(screen.getByText("Admin Access Required")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Back to Agent Tasks/i })
    ).toBeInTheDocument();
    unmount();

    const fetchMock = vi
      .fn()
      .mockImplementation((_url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                detail: {
                  code: "org_admin_required",
                  message: "Admin permission (org:admin) is required.",
                },
              }),
              { status: 403 }
            )
          );
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BreadcrumbProvider>
        <SettingsView canPersistToApi getToken={async () => "tok"} />
      </BreadcrumbProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: /Save Changes/i }));
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Admin permission (org:admin) is required."
      );
    });
  });

  it("renders read-only Guardrail Overrides for non-admins and sends null on Clear Overrides (covers: AC-1, AC-7)", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/v1/repositories")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                items: [
                  {
                    id: "repo-2",
                    name: "core",
                    full_name: "acme/core",
                    default_branch: "main",
                    is_private: false,
                  },
                ],
              }),
              { status: 200 }
            )
          );
        }
        if (
          url.endsWith("/api/v1/repositories/repo-2/guardrails") &&
          !init?.method
        ) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                repo_id: "repo-2",
                org_defaults: {
                  protected_branches: ["main"],
                  protected_branch_guard: true,
                  require_approval_for: ["destructive_shell"],
                  max_task_cost_cents: 500,
                  max_monthly_org_cost_cents: 10000,
                  timeout_minutes: 10,
                  max_cycles: 3,
                  network_egress_mode: "off_after_install",
                  allowed_egress_domains: [],
                  large_diff_lines_threshold: 500,
                },
                repo_overrides: { max_task_cost_cents: 300 },
                effective_policy: {
                  protected_branches: ["main"],
                  protected_branch_guard: true,
                  require_approval_for: ["destructive_shell"],
                  max_task_cost_cents: 300,
                  max_monthly_org_cost_cents: 10000,
                  timeout_minutes: 10,
                  max_cycles: 3,
                  network_egress_mode: "off_after_install",
                  allowed_egress_domains: [],
                  large_diff_lines_threshold: 500,
                },
              }),
              { status: 200 }
            )
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              repo_id: "repo-2",
              repo_overrides: {},
              effective_policy: {
                protected_branches: ["main"],
                protected_branch_guard: true,
                require_approval_for: ["destructive_shell"],
                max_task_cost_cents: 500,
                max_monthly_org_cost_cents: 10000,
                timeout_minutes: 10,
                max_cycles: 3,
                network_egress_mode: "off_after_install",
                allowed_egress_domains: [],
                large_diff_lines_threshold: 500,
              },
            }),
            { status: 200 }
          )
        );
      });
    vi.stubGlobal("fetch", fetchMock);

    // Non-admin read-only drawer
    const { unmount } = render(
      <BreadcrumbProvider>
        <RepositoriesView
          canLoadFromApi
          isAdmin={false}
          getToken={async () => "tok"}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("core")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardrails/i }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("300")).toBeDisabled();
    });
    expect(
      screen.queryByRole("button", { name: /Save Overrides/i })
    ).not.toBeInTheDocument();
    unmount();

    // Admin clears overrides and submits null values
    render(
      <BreadcrumbProvider>
        <RepositoriesView canLoadFromApi isAdmin getToken={async () => "tok"} />
      </BreadcrumbProvider>
    );
    await waitFor(() => {
      expect(screen.getByText("core")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardrails/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Clear Overrides/i })
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Clear Overrides/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save Overrides/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/repositories/repo-2/guardrails"),
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"max_task_cost_cents":null'),
        })
      );
    });
  });

  it("hides approval buttons for non-admins and renders preserved partial_diff (covers: AC-6, AC-7)", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/api/v1/tasks/task-2")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              id: "task-2",
              title: "Halted task",
              repo_full_name: "acme/core",
              branch_name: "feat/x",
              status: "awaiting_input",
              interruption_prompt: "Approve?",
              interruption_type: "approval",
              pending_approval: {
                approval_id: "app-2",
                risk_category: "sensitive_path_edit",
                action_type: "sandbox_file_write",
                action_summary: "Write .env",
                action_payload: { path: ".env" },
                expires_at: "2026-11-27T12:00:00Z",
              },
              budget_summary: {
                task_cost_cents: 500,
                max_task_cost_cents: 500,
                tokens_used: 18000,
                partial_diff: "diff --git a/x.py b/x.py\n+x = 1\n",
              },
            }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BreadcrumbProvider>
        <TaskDetailClient
          taskId="task-2"
          orgId="org-1"
          isAdmin={false}
          getToken={async () => "tok"}
        />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(
        screen.getByText(/must approve or reject this risky action/i)
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: /Approve Action/i })
    ).not.toBeInTheDocument();
    expect(screen.getByText("View Preserved Partial Diff")).toBeInTheDocument();
    expect(screen.getByText(/\+x = 1/)).toBeInTheDocument();
  });
});
