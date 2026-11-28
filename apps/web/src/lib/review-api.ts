import {
  dispatchOrgForbiddenEvent,
  extractOrgForbiddenDetail,
} from "@/lib/org-recovery";

export type RuleSeverity = "critical" | "major" | "minor" | "info";
export type RuleCategory =
  "security" | "bug" | "performance" | "architecture" | "style";

export interface ReviewRuleDto {
  id: string;
  org_id: string;
  repo_id: string | null;
  title: string;
  instruction: string;
  severity: RuleSeverity;
  category: RuleCategory;
  path_globs: string[];
  is_enabled: boolean;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EffectiveReviewRuleDto {
  id: string;
  org_id: string;
  repo_id: string | null;
  scope: "org" | "repo";
  title: string;
  instruction: string;
  base_severity: RuleSeverity;
  severity: RuleSeverity;
  category: RuleCategory;
  path_globs: string[];
  base_is_enabled: boolean;
  is_enabled: boolean;
  has_override: boolean;
  override_is_enabled: boolean | null;
  override_severity: RuleSeverity | null;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ReviewExampleDto {
  id: string;
  org_id: string;
  repo_id: string;
  pr_number: number;
  pr_url: string;
  pr_title: string;
  classification: "good" | "bad";
  guidance_note: string;
  modified_files: string[];
  cached_diff_summary?: string | null;
  cached_token_count: number;
  cached_at?: string | null;
  created_by: string;
}

export interface LearnedPreferenceDto {
  id: string;
  org_id: string;
  repo_id: string;
  rule_id: string | null;
  pattern_key: string;
  instruction: string;
  dismiss_count: number;
  accept_count: number;
  consecutive_dismissals: number;
  status: "active" | "dampened" | "suppressed";
  last_feedback_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PRReviewFindingDto {
  id: string;
  file_path: string;
  line_number: number;
  start_line?: number | null;
  side: string;
  severity: RuleSeverity;
  category: RuleCategory;
  title: string;
  message: string;
  suggested_patch?: string | null;
  github_comment_id?: number | null;
  status: string;
  rule_id?: string | null;
  feedback_state: "none" | "accepted" | "dismissed";
}

export interface PRReviewSummaryDto {
  id: string;
  org_id: string;
  repo_id: string;
  repo_full_name?: string | null;
  pr_number: number;
  pr_title: string;
  pr_author: string;
  head_commit_sha: string;
  base_commit_sha: string;
  status: string;
  verdict?: string | null;
  summary?: string | null;
  github_review_id?: number | null;
  context_token_count: number;
  model_name: string;
  execution_duration_ms?: number | null;
  error_message?: string | null;
  findings_count?: number;
  created_at?: string | null;
}

export interface PRReviewDetailDto extends PRReviewSummaryDto {
  findings: PRReviewFindingDto[];
}

export interface FindingFeedbackResponseDto {
  finding: {
    id: string;
    rule_id: string | null;
    feedback_state: "none" | "accepted" | "dismissed";
    status: string;
  };
  learned_preference: LearnedPreferenceDto | null;
  applied: boolean;
  deduplicated: boolean;
}

export interface AnalyticsDailyPointDto {
  date: string;
  pr_review_cost_cents: number;
  autonomous_cost_cents: number;
  total_cost_cents: number;
  pr_review_p50_ms: number;
  task_p50_ms: number;
}

export interface AnalyticsTopRuleDto {
  rule_id: string;
  title: string;
  severity: RuleSeverity;
  category: RuleCategory;
  triggered_count: number;
  accepted_count: number;
  dismissed_count: number;
}

export interface AnalyticsOverviewDto {
  days: number;
  repo_id: string | null;
  kpis: {
    total_reviews: number;
    total_task_runs: number;
    turnaround_p50_ms: number | null;
    turnaround_p95_ms: number | null;
    task_turnaround_p50_ms: number | null;
    task_turnaround_p95_ms: number | null;
    total_findings: number;
    accepted_findings: number;
    dismissed_findings: number;
    acceptance_rate: number | null;
    total_cost_cents: number;
    pr_review_cost_cents: number;
    autonomous_cost_cents: number;
  };
  findings_by_severity: Record<string, number>;
  findings_by_category: Record<string, number>;
  top_rules: AnalyticsTopRuleDto[];
  daily_series: AnalyticsDailyPointDto[];
}

export function getAgentApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";
}

export async function resolveClientAuthToken(
  getToken?: () => Promise<string | null>
): Promise<string | null> {
  if (getToken) {
    return await getToken();
  }
  if (typeof window !== "undefined" && window.Clerk?.session?.getToken) {
    return await window.Clerk.session.getToken();
  }
  return null;
}

export async function agentFetchJson<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    token?: string | null;
  } = {}
): Promise<
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; message: string }
> {
  const baseUrl = getAgentApiBaseUrl();
  const headers: Record<string, string> = {};
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${baseUrl}${path}`, {
    method: options.method ?? "GET",
    credentials: "include",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 204) {
    return { ok: true, status: 204, data: undefined as T };
  }

  const raw = await res.json().catch(() => null);
  if (res.status === 403) {
    const detail = extractOrgForbiddenDetail(raw);
    if (detail) {
      dispatchOrgForbiddenEvent(detail);
    }
    const msg =
      (raw as { detail?: { message?: string } | string } | null)?.detail &&
      typeof (raw as { detail?: { message?: string } | string }).detail ===
        "object"
        ? ((raw as { detail?: { message?: string } }).detail?.message ??
          "Access denied.")
        : typeof (raw as { detail?: string } | null)?.detail === "string"
          ? (raw as { detail: string }).detail
          : "Access denied.";
    return { ok: false, status: 403, message: msg };
  }

  if (!res.ok) {
    const detail = (raw as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail.length > 0
          ? String((detail[0] as { msg?: string })?.msg ?? "Validation failed.")
          : `Request failed (${res.status}).`;
    return { ok: false, status: res.status, message };
  }

  return { ok: true, status: res.status, data: raw as T };
}

export function severityToneClass(severity: string): string {
  switch (severity) {
    case "critical":
      return "border-rose-500/40 bg-rose-500/15 text-rose-300";
    case "major":
      return "border-amber-500/40 bg-amber-500/15 text-amber-300";
    case "minor":
      return "border-sky-500/40 bg-sky-500/15 text-sky-300";
    default:
      return "border-zinc-700 bg-zinc-800/80 text-zinc-300";
  }
}
