import { render, screen, act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import * as React from "react";
import { NextRequest } from "next/server";

const mockRedirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT:${url}`);
});
const mockAuth = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (url: string) => mockRedirect(url),
  usePathname: () => "/tasks",
  useRouter: () => ({
    push: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: () => mockAuth(),
  clerkMiddleware:
    (handler?: (auth: () => Promise<unknown>, req: NextRequest) => unknown) =>
    async (req: NextRequest) => {
      if (!handler) {
        return undefined;
      }
      return await handler(() => mockAuth(), req);
    },
}));

vi.mock("@clerk/nextjs", () => ({
  OrganizationSwitcher: ({ hidePersonal }: { hidePersonal?: boolean }) => (
    <div
      data-testid="clerk-org-switcher"
      data-hide-personal={String(Boolean(hidePersonal))}
    >
      OrganizationSwitcher
    </div>
  ),
  OrganizationList: ({ hidePersonal }: { hidePersonal?: boolean }) => (
    <div
      data-testid="clerk-org-list"
      data-hide-personal={String(Boolean(hidePersonal))}
    >
      OrganizationList
    </div>
  ),
  UserButton: () => <div data-testid="clerk-user-button">UserButton</div>,
  SignIn: () => <div data-testid="clerk-sign-in">SignIn</div>,
  SignUp: () => <div data-testid="clerk-sign-up">SignUp</div>,
  TaskChooseOrganization: () => (
    <div data-testid="clerk-task-choose-org">TaskChooseOrganization</div>
  ),
  useSession: () => ({
    session: { reload: vi.fn() },
  }),
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: vi.fn(async (_url, options) => {
    if (options.onopen) {
      await options.onopen({
        ok: false,
        status: 403,
        json: async () => ({
          detail: {
            code: "org_inactive",
            message: "Organization inactive in Clerk.",
          },
        }),
      });
    }
  }),
}));

import { GET as healthGET } from "../src/app/api/health/route";
import { ClerkConfigurationError } from "../src/lib/clerk-config";
import { requireConsoleOrg } from "../src/lib/clerk-server";
import proxy from "../src/proxy";
import AuthLayout from "../src/app/(auth)/layout";
import { ConsoleLayout } from "../src/components/layout/console-layout";
import { Sidebar } from "../src/components/layout/sidebar";
import { SettingsUnauthorizedView } from "../src/app/(console)/settings/settings-view";
import { BreadcrumbProvider } from "../src/components/layout/breadcrumb-context";
import { TaskDetailClient } from "../src/app/(console)/tasks/[id]/task-detail-client";

const ORIGINAL_ENV = { ...process.env };

describe("Clerk Authentication, Route Protection & Recovery UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env = { ...ORIGINAL_ENV };
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("GET /api/health always returns 200 {status: ok} even with placeholder keys in production (AC-1)", async () => {
    vi.stubEnv("NODE_ENV", "production");
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY = "pk_test_placeholder";
    process.env.CLERK_SECRET_KEY = "sk_test_placeholder";

    const res = await healthGET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });

    const req = new NextRequest("http://localhost:3000/api/health");
    const proxyRes = await proxy(req, {} as never);
    expect(proxyRes?.status).toBe(200);
  });

  it("proxy.ts fails closed with HTTP 500 in production when Clerk keys are placeholder (AC-1)", async () => {
    vi.stubEnv("NODE_ENV", "production");
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY = "pk_test_placeholder";
    process.env.CLERK_SECRET_KEY = "sk_test_placeholder";

    const req = new NextRequest("http://localhost:3000/tasks");
    const res = await proxy(req, {} as never);
    expect(res?.status).toBe(500);
  });

  it("proxy.ts redirects unauthenticated visitors with 307 and pending/no-org users to onboarding (AC-1, AC-3)", async () => {
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY =
      "pk_test_real_key_1234567890abcdef";
    process.env.CLERK_SECRET_KEY = "sk_test_real_key_1234567890abcdef";

    // Unauthenticated -> 307 to /sign-in
    mockAuth.mockResolvedValue({
      userId: null,
      orgId: null,
      sessionStatus: null,
    });
    const unauthReq = new NextRequest("http://localhost:3000/tasks");
    const unauthRes = await proxy(unauthReq, {} as never);
    expect(unauthRes?.status).toBe(307);
    expect(unauthRes?.headers.get("location")).toContain("/sign-in");

    // Signed in without org / pending -> 307 to /onboarding/organization
    mockAuth.mockResolvedValue({
      userId: "user_123",
      orgId: null,
      sessionStatus: "pending",
    });
    const pendingReq = new NextRequest("http://localhost:3000/tasks");
    const pendingRes = await proxy(pendingReq, {} as never);
    expect(pendingRes?.status).toBe(307);
    expect(pendingRes?.headers.get("location")).toContain(
      "/onboarding/organization"
    );
  });

  it("requireConsoleOrg enforces production fail-closed, placeholder bypass, and org/admin guards (AC-1, AC-3, AC-4)", async () => {
    // 1. Production with placeholder keys -> throws ClerkConfigurationError (500)
    vi.stubEnv("NODE_ENV", "production");
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY = "pk_test_placeholder";
    process.env.CLERK_SECRET_KEY = "sk_test_placeholder";
    await expect(requireConsoleOrg()).rejects.toBeInstanceOf(
      ClerkConfigurationError
    );

    // 2. Non-prod placeholder bypass -> returns bypass session
    vi.stubEnv("NODE_ENV", "test");
    const bypass = await requireConsoleOrg();
    expect(bypass.isPlaceholderBypass).toBe(true);
    expect(bypass.isAdmin).toBe(true);

    // 3. Configured keys + unauthenticated -> redirect /sign-in
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY =
      "pk_test_real_key_1234567890abcdef";
    process.env.CLERK_SECRET_KEY = "sk_test_real_key_1234567890abcdef";
    mockAuth.mockResolvedValue({
      userId: null,
      orgId: null,
      sessionStatus: null,
      has: () => false,
    });
    await expect(requireConsoleOrg()).rejects.toThrow("NEXT_REDIRECT:/sign-in");

    // 4. Configured keys + active org member -> returns isAdmin: false
    mockAuth.mockResolvedValue({
      userId: "user_1",
      orgId: "org_1",
      orgSlug: "acme",
      orgRole: "org:member",
      sessionStatus: "active",
      has: ({ role }: { role?: string }) => role === "org:member",
    });
    const memberSession = await requireConsoleOrg();
    expect(memberSession.orgId).toBe("org_1");
    expect(memberSession.isAdmin).toBe(false);
  });

  it("AuthLayout hides Sidebar/Header while ConsoleLayout mounts OrgRecoveryDialog on 403 (AC-2, AC-7)", async () => {
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY =
      "pk_test_real_key_1234567890abcdef";

    const { unmount } = render(
      <AuthLayout>
        <div>Sign in panel</div>
      </AuthLayout>
    );
    expect(screen.getByText("Sign in panel")).toBeInTheDocument();
    expect(screen.queryByTestId("clerk-org-switcher")).not.toBeInTheDocument();
    unmount();

    render(
      <ConsoleLayout>
        <div>Console content</div>
      </ConsoleLayout>
    );
    expect(screen.getByTestId("clerk-org-switcher")).toHaveAttribute(
      "data-hide-personal",
      "true"
    );
    expect(screen.getByTestId("clerk-user-button")).toBeInTheDocument();

    // Dispatch 403 org_inactive recovery event -> opens OrganizationList dialog
    act(() => {
      window.dispatchEvent(
        new CustomEvent("aoa:org-forbidden", {
          detail: {
            code: "org_inactive",
            message: "Organization inactive in Clerk.",
          },
        })
      );
    });

    await waitFor(() => {
      expect(
        screen.getByText("Organization Inactive or Removed")
      ).toBeInTheDocument();
      expect(screen.getByTestId("clerk-org-list")).toHaveAttribute(
        "data-hide-personal",
        "true"
      );
      expect(
        screen.getByRole("button", { name: /Reload session/i })
      ).toBeInTheDocument();
    });
  });

  it("Sidebar renders OrganizationSwitcher and SettingsUnauthorizedView explains org:admin gate (AC-3, AC-4)", () => {
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY =
      "pk_test_real_key_1234567890abcdef";

    render(<Sidebar />);
    expect(screen.getByTestId("clerk-org-switcher")).toBeInTheDocument();

    render(
      <BreadcrumbProvider>
        <SettingsUnauthorizedView />
      </BreadcrumbProvider>
    );
    expect(screen.getByText("Admin Access Required")).toBeInTheDocument();
    expect(screen.getByText("org:admin")).toBeInTheDocument();
  });

  it("TaskDetailClient omits ?org_id= from FastAPI calls and triggers recovery on 403 org_inactive (AC-4, AC-7)", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        detail: {
          code: "org_inactive",
          message: "Organization inactive.",
        },
      }),
    });
    global.fetch = fetchSpy;

    const eventListener = vi.fn();
    window.addEventListener("aoa:org-forbidden", eventListener);

    try {
      render(
        <BreadcrumbProvider>
          <TaskDetailClient
            taskId="018f6c38-8921-7000-8000-000000000001"
            orgId="org_clerk_123"
            authToken="tok_123"
          />
        </BreadcrumbProvider>
      );

      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalled();
        expect(eventListener).toHaveBeenCalled();
      });

      for (const call of fetchSpy.mock.calls) {
        expect(String(call[0])).not.toContain("org_id=");
      }
    } finally {
      window.removeEventListener("aoa:org-forbidden", eventListener);
    }
  });
});
