import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getTableName } from "drizzle-orm";
import * as React from "react";
import {
  prReviewFindings,
  pullRequestReviews,
  repositories,
  reviewExamples,
  reviewFindingFeedback,
  reviewLearnedPreferences,
  reviewRuleOverrides,
  reviewRules,
} from "../src/db/schema";
import { Sidebar } from "../src/components/layout/sidebar";
import { BreadcrumbProvider } from "../src/components/layout/breadcrumb-context";
import { AnalyticsView } from "../src/app/(console)/analytics/analytics-view";
import { ReviewsView } from "../src/app/(console)/reviews/reviews-view";
import { SettingsView } from "../src/app/(console)/settings/settings-view";
import { RepositoriesView } from "../src/app/(console)/repositories/repositories-view";

vi.mock("../src/components/ui/sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
  Toaster: () => null,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/analytics",
  useRouter: () => ({ push: vi.fn() }),
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

describe("Spec 0009 Drizzle Schema & Console UI (AC-7)", () => {
  it("exports Spec 0005 backfill and Spec 0009 Drizzle tables", () => {
    expect(repositories.reviewSettings).toBeDefined();
    expect(getTableName(pullRequestReviews)).toBe("pull_request_reviews");
    expect(getTableName(prReviewFindings)).toBe("pr_review_findings");
    expect(prReviewFindings.ruleId).toBeDefined();
    expect(prReviewFindings.feedbackState).toBeDefined();
    expect(getTableName(reviewRules)).toBe("review_rules");
    expect(getTableName(reviewRuleOverrides)).toBe("review_rule_overrides");
    expect(getTableName(reviewExamples)).toBe("review_examples");
    expect(getTableName(reviewFindingFeedback)).toBe("review_finding_feedback");
    expect(getTableName(reviewLearnedPreferences)).toBe(
      "review_learned_preferences"
    );
  });

  it("renders Reviews and Analytics navigation links in Sidebar", () => {
    render(<Sidebar />);
    expect(screen.getByRole("link", { name: /Reviews/i })).toHaveAttribute(
      "href",
      "/reviews"
    );
    expect(screen.getByRole("link", { name: /Analytics/i })).toHaveAttribute(
      "href",
      "/analytics"
    );
  });

  it("renders AnalyticsView KPIs, SVG charts, timeframe switches, and empty states", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/v1/repositories")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [{ id: "repo-1", full_name: "acme/core" }],
            }),
            { status: 200 }
          )
        );
      }
      if (url.includes("/api/v1/analytics/overview")) {
        const is7d = url.includes("days=7");
        return Promise.resolve(
          new Response(
            JSON.stringify({
              days: is7d ? 7 : 30,
              repo_id: null,
              kpis: {
                total_reviews: is7d ? 2 : 12,
                total_task_runs: 5,
                turnaround_p50_ms: 1850,
                turnaround_p95_ms: 4200,
                task_turnaround_p50_ms: 15000,
                task_turnaround_p95_ms: 32000,
                total_findings: 8,
                accepted_findings: 6,
                dismissed_findings: 2,
                acceptance_rate: 0.75,
                total_cost_cents: 450,
                pr_review_cost_cents: 150,
                autonomous_cost_cents: 300,
              },
              findings_by_severity: {
                critical: 1,
                major: 3,
                minor: 3,
                info: 1,
              },
              findings_by_category: {
                security: 2,
                bug: 3,
                performance: 1,
                architecture: 2,
                style: 0,
              },
              top_rules: [
                {
                  rule_id: "rule-1",
                  title: "Parameterized SQL",
                  severity: "critical",
                  category: "security",
                  triggered_count: 4,
                  accepted_count: 3,
                  dismissed_count: 1,
                },
              ],
              daily_series: [
                {
                  date: "2026-11-27",
                  pr_review_cost_cents: 150,
                  autonomous_cost_cents: 300,
                  total_cost_cents: 450,
                  pr_review_p50_ms: 1850,
                  task_p50_ms: 15000,
                },
              ],
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
        <AnalyticsView canLoadFromApi getToken={async () => "tok"} />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("75%")).toBeInTheDocument();
      expect(screen.getByText("$4.50")).toBeInTheDocument();
      expect(screen.getByText("Parameterized SQL")).toBeInTheDocument();
    });

    expect(
      screen.getByRole("img", { name: /Daily AI Spend stacked bar chart/i })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "7d" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("days=7"),
        expect.any(Object)
      );
    });
  });

  it("renders ReviewsView and submits finding Dismiss feedback with reason & remember toggle", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, init?: RequestInit) => {
        if (url.includes("/api/v1/repositories")) {
          return Promise.resolve(
            new Response(JSON.stringify({ items: [] }), { status: 200 })
          );
        }
        if (url.includes("/api/v1/reviews/findings/finding-1/feedback")) {
          expect(init?.method).toBe("POST");
          const body = JSON.parse(String(init?.body));
          expect(body.feedback_type).toBe("dismissed");
          expect(body.reason).toBe("Intentional helper");
          expect(body.remember_preference).toBe(true);
          return Promise.resolve(
            new Response(
              JSON.stringify({
                finding: {
                  id: "finding-1",
                  rule_id: null,
                  feedback_state: "dismissed",
                  status: "dismissed",
                },
                learned_preference: {
                  id: "pref-1",
                  org_id: "org-1",
                  repo_id: "repo-1",
                  rule_id: null,
                  pattern_key: "style:src",
                  instruction: "Intentional helper",
                  dismiss_count: 2,
                  accept_count: 0,
                  consecutive_dismissals: 2,
                  status: "dampened",
                },
                applied: true,
                deduplicated: false,
              }),
              { status: 200 }
            )
          );
        }
        if (url.includes("/api/v1/reviews/rev-1")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: "rev-1",
                org_id: "org-1",
                repo_id: "repo-1",
                pr_number: 12,
                pr_title: "Add billing webhook",
                pr_author: "alice",
                head_commit_sha: "a",
                base_commit_sha: "b",
                status: "completed",
                verdict: "comment",
                context_token_count: 3400,
                model_name: "claude-sonnet-4",
                findings: [
                  {
                    id: "finding-1",
                    file_path: "src/billing.ts",
                    line_number: 44,
                    side: "RIGHT",
                    severity: "minor",
                    category: "style",
                    title: "Prefer named export",
                    message: "Consider named export here",
                    status: "open",
                    feedback_state: "none",
                  },
                ],
              }),
              { status: 200 }
            )
          );
        }
        if (url.includes("/api/v1/reviews?")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                items: [
                  {
                    id: "rev-1",
                    org_id: "org-1",
                    repo_id: "repo-1",
                    repo_full_name: "acme/core",
                    pr_number: 12,
                    pr_title: "Add billing webhook",
                    pr_author: "alice",
                    head_commit_sha: "a",
                    base_commit_sha: "b",
                    status: "completed",
                    verdict: "comment",
                    context_token_count: 3400,
                    model_name: "claude-sonnet-4",
                    execution_duration_ms: 900,
                    findings_count: 1,
                  },
                ],
                total: 1,
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
        <ReviewsView canLoadFromApi getToken={async () => "tok"} />
      </BreadcrumbProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Prefer named export")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
    fireEvent.change(screen.getByLabelText(/Optional reason/i), {
      target: { value: "Intentional helper" },
    });
    fireEvent.click(
      screen.getByLabelText(/Remember team preference across future reviews/i)
    );
    fireEvent.click(screen.getByRole("button", { name: /Confirm Dismiss/i }));

    await waitFor(() => {
      expect(screen.getByText("dismissed")).toBeInTheDocument();
    });
  });

  it("renders Organization Review Guidelines on SettingsView", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, init?: RequestInit) => {
        if (
          url.endsWith("/api/v1/organizations/review-rules?limit=100") &&
          (!init?.method || init.method === "GET")
        ) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                items: [
                  {
                    id: "rule-org-1",
                    org_id: "org-1",
                    repo_id: null,
                    title: "Validate inputs",
                    instruction: "Validate request payloads with Zod/Pydantic.",
                    severity: "major",
                    category: "security",
                    path_globs: ["**/*"],
                    is_enabled: true,
                    created_by: "u-1",
                  },
                ],
                total: 1,
              }),
              { status: 200 }
            )
          );
        }
        if (
          url.endsWith("/api/v1/organizations/review-rules") &&
          init?.method === "POST"
        ) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: "rule-org-2",
                org_id: "org-1",
                repo_id: null,
                title: "No console.log",
                instruction: "Use structured logger.",
                severity: "minor",
                category: "style",
                path_globs: ["apps/web/**/*"],
                is_enabled: true,
                created_by: "u-1",
              }),
              { status: 201 }
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

    await waitFor(() => {
      expect(screen.getByText("Validate inputs")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Rule Title/i), {
      target: { value: "No console.log" },
    });
    fireEvent.change(screen.getByLabelText(/Instruction/i), {
      target: { value: "Use structured logger." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add Guideline/i }));

    await waitFor(() => {
      expect(screen.getByText("No console.log")).toBeInTheDocument();
    });
  });

  it("renders RepositoriesView 4-tab drawer and enforces read-only for non-admins", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/api/v1/repositories")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [
                {
                  id: "repo-1",
                  name: "core",
                  full_name: "acme/core",
                  default_branch: "main",
                  is_private: true,
                },
              ],
              total: 1,
            }),
            { status: 200 }
          )
        );
      }
      if (url.endsWith("/review-rules")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [], active_count: 0 }), {
            status: 200,
          })
        );
      }
      if (url.endsWith("/review-examples")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [] }), { status: 200 })
        );
      }
      if (url.endsWith("/review-preferences?limit=100")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [] }), { status: 200 })
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            org_defaults: {
              protected_branches: ["main"],
              protected_branch_guard: true,
              require_approval_for: [],
              max_task_cost_cents: 500,
              max_monthly_org_cost_cents: 10000,
              timeout_minutes: 10,
              max_cycles: 3,
              network_egress_mode: "off_after_install",
              allowed_egress_domains: [],
              large_diff_lines_threshold: 500,
            },
            repo_overrides: {},
            effective_policy: {
              protected_branches: ["main"],
              protected_branch_guard: true,
              require_approval_for: [],
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

    render(
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
      expect(
        screen.getByRole("tab", { name: /Rules & Overrides/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("tab", { name: /Example PRs/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("tab", { name: /Learned Preferences/i })
      ).toBeInTheDocument();
    });

    // Non-admin read-only: Save Overrides button should not exist
    expect(
      screen.queryByRole("button", { name: /Save Overrides/i })
    ).not.toBeInTheDocument();
  });
});
