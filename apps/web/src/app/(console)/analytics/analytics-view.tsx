"use client";

import * as React from "react";
import {
  BarChart3,
  Clock,
  CheckCircle2,
  DollarSign,
  RefreshCw,
  AlertCircle,
  ShieldCheck,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";
import {
  agentFetchJson,
  resolveClientAuthToken,
  severityToneClass,
  type AnalyticsOverviewDto,
} from "@/lib/review-api";
import { cn } from "@/lib/utils";

export interface AnalyticsViewProps {
  canLoadFromApi?: boolean;
  getToken?: () => Promise<string | null>;
}

interface RepoOption {
  id: string;
  full_name: string;
}

const MOCK_ANALYTICS: AnalyticsOverviewDto = {
  days: 30,
  repo_id: null,
  kpis: {
    total_reviews: 0,
    total_task_runs: 0,
    turnaround_p50_ms: null,
    turnaround_p95_ms: null,
    task_turnaround_p50_ms: null,
    task_turnaround_p95_ms: null,
    total_findings: 0,
    accepted_findings: 0,
    dismissed_findings: 0,
    acceptance_rate: null,
    total_cost_cents: 0,
    pr_review_cost_cents: 0,
    autonomous_cost_cents: 0,
  },
  findings_by_severity: { critical: 0, major: 0, minor: 0, info: 0 },
  findings_by_category: {
    security: 0,
    bug: 0,
    performance: 0,
    architecture: 0,
    style: 0,
  },
  top_rules: [],
  daily_series: [],
};

function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "No data";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function AnalyticsView({
  canLoadFromApi = false,
  getToken,
}: AnalyticsViewProps) {
  useBreadcrumbs([{ label: "Analytics" }]);

  const [days, setDays] = React.useState<7 | 30 | 90>(30);
  const [repoId, setRepoId] = React.useState<string>("all");
  const [repos, setRepos] = React.useState<RepoOption[]>([]);
  const [data, setData] = React.useState<AnalyticsOverviewDto>(MOCK_ANALYTICS);
  const [isLoading, setIsLoading] = React.useState(canLoadFromApi);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    if (!canLoadFromApi) return;
    let active = true;
    const loadRepos = async () => {
      try {
        const token = await resolveClientAuthToken(getToken);
        const res = await agentFetchJson<{ items?: RepoOption[] }>(
          "/api/v1/repositories?limit=100",
          { token }
        );
        if (res.ok && active) {
          setRepos(res.data.items ?? []);
        }
      } catch {
        // Non-blocking repo filter load
      }
    };
    void loadRepos();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, getToken]);

  React.useEffect(() => {
    if (!canLoadFromApi) return;
    let active = true;
    const loadOverview = async () => {
      setIsLoading(true);
      setErrorMsg(null);
      try {
        const token = await resolveClientAuthToken(getToken);
        const query = new URLSearchParams({ days: String(days) });
        if (repoId !== "all") {
          query.set("repo_id", repoId);
        }
        const res = await agentFetchJson<AnalyticsOverviewDto>(
          `/api/v1/analytics/overview?${query.toString()}`,
          { token }
        );
        if (!active) return;
        if (res.ok) {
          setData(res.data);
        } else {
          setErrorMsg(res.message);
        }
      } catch {
        if (active) {
          setErrorMsg("Unable to reach agent engine for analytics.");
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void loadOverview();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, days, repoId, reloadNonce, getToken]);

  const series = data.daily_series ?? [];
  const maxDailyCost = Math.max(
    1,
    ...series.map((d) => d.total_cost_cents || 0)
  );
  const maxDailyLatency = Math.max(
    1,
    ...series.map((d) => Math.max(d.pr_review_p50_ms || 0, d.task_p50_ms || 0))
  );
  const hasAnyCost = series.some((d) => d.total_cost_cents > 0);
  const hasAnyLatency = series.some(
    (d) => d.pr_review_p50_ms > 0 || d.task_p50_ms > 0
  );

  const totalFindings = Math.max(1, data.kpis.total_findings);

  const prPoints = series
    .map((pt, idx) => {
      const x =
        series.length <= 1 ? 280 : 20 + (idx / (series.length - 1)) * 520;
      const y = 130 - ((pt.pr_review_p50_ms || 0) / maxDailyLatency) * 105;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const taskPoints = series
    .map((pt, idx) => {
      const x =
        series.length <= 1 ? 280 : 20 + (idx / (series.length - 1)) * 520;
      const y = 130 - ((pt.task_p50_ms || 0) / maxDailyLatency) * 105;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Quality & Turnaround Analytics
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Track code review turnaround, autonomous task execution speed,
            finding acceptance rate, and daily AI spend.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div
            role="group"
            aria-label="Analytics timeframe"
            className="inline-flex rounded-lg border border-border bg-card p-1"
          >
            {([7, 30, 90] as const).map((windowDays) => (
              <button
                key={windowDays}
                type="button"
                aria-pressed={days === windowDays}
                onClick={() => setDays(windowDays)}
                className={cn(
                  "px-3 py-1 text-xs font-mono rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  days === windowDays
                    ? "bg-accent text-accent-foreground font-semibold"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {windowDays}d
              </button>
            ))}
          </div>

          <Select value={repoId} onValueChange={setRepoId}>
            <SelectTrigger
              aria-label="Filter analytics by repository"
              className="w-56 text-xs"
            >
              <SelectValue placeholder="All Repositories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Repositories</SelectItem>
              {repos.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setReloadNonce((n) => n + 1)}
            className="gap-1.5 text-xs"
            aria-label="Refresh analytics"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Refresh</span>
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((n) => (
            <div
              key={n}
              className="h-28 rounded-xl border border-border bg-card animate-pulse"
            />
          ))}
        </div>
      )}

      {!isLoading && errorMsg && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="py-5 flex items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-2 text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setReloadNonce((n) => n + 1)}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {!isLoading && !errorMsg && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="text-xs flex items-center justify-between">
                  <span>PR Review Turnaround</span>
                  <Clock className="h-3.5 w-3.5 text-emerald-400" />
                </CardDescription>
                <CardTitle className="text-2xl font-mono">
                  {formatDurationMs(data.kpis.turnaround_p50_ms)}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-[11px] text-muted-foreground font-mono">
                p95: {formatDurationMs(data.kpis.turnaround_p95_ms)} ·{" "}
                {data.kpis.total_reviews} reviews
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="text-xs flex items-center justify-between">
                  <span>Autonomous Task Active</span>
                  <BarChart3 className="h-3.5 w-3.5 text-sky-400" />
                </CardDescription>
                <CardTitle className="text-2xl font-mono">
                  {formatDurationMs(data.kpis.task_turnaround_p50_ms)}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-[11px] text-muted-foreground font-mono">
                p95: {formatDurationMs(data.kpis.task_turnaround_p95_ms)} ·{" "}
                {data.kpis.total_task_runs} runs
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="text-xs flex items-center justify-between">
                  <span>Finding Acceptance Rate</span>
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                </CardDescription>
                <CardTitle className="text-2xl font-mono">
                  {data.kpis.acceptance_rate !== null
                    ? `${Math.round(data.kpis.acceptance_rate * 100)}%`
                    : "No feedback"}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-[11px] text-muted-foreground font-mono">
                {data.kpis.accepted_findings} accepted ·{" "}
                {data.kpis.dismissed_findings} dismissed
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="text-xs flex items-center justify-between">
                  <span>Total AI Spend ({days}d)</span>
                  <DollarSign className="h-3.5 w-3.5 text-amber-400" />
                </CardDescription>
                <CardTitle className="text-2xl font-mono">
                  {formatCents(data.kpis.total_cost_cents)}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-[11px] text-muted-foreground font-mono">
                Reviews: {formatCents(data.kpis.pr_review_cost_cents)} · Agents:{" "}
                {formatCents(data.kpis.autonomous_cost_cents)}
              </CardContent>
            </Card>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Daily AI Spend Stacked Bar Chart */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Daily AI Spend (PR Review vs Autonomous Agents)
                </CardTitle>
                <CardDescription className="text-xs">
                  UTC daily breakdown in cents across {days} days.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!hasAnyCost ? (
                  <div className="h-44 flex flex-col items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
                    <span>No AI spend recorded in this {days} day window.</span>
                    <span className="text-[11px] mt-1">
                      Run a pull request review or autonomous task to populate
                      daily spend.
                    </span>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <svg
                      viewBox="0 0 560 150"
                      role="img"
                      aria-label="Daily AI Spend stacked bar chart"
                      className="w-full h-44 overflow-visible"
                    >
                      <line
                        x1="16"
                        y1="130"
                        x2="544"
                        y2="130"
                        stroke="currentColor"
                        className="text-border"
                        strokeWidth="1"
                      />
                      {series.map((pt, idx) => {
                        const slotWidth = 520 / Math.max(1, series.length);
                        const barWidth = Math.max(3, slotWidth * 0.68);
                        const x = 20 + idx * slotWidth;
                        const totalH =
                          (pt.total_cost_cents / maxDailyCost) * 105;
                        const prH =
                          (pt.pr_review_cost_cents / maxDailyCost) * 105;
                        const autoH = Math.max(0, totalH - prH);
                        return (
                          <g key={pt.date}>
                            <title>
                              {pt.date}: PR Review{" "}
                              {formatCents(pt.pr_review_cost_cents)}, Agents{" "}
                              {formatCents(pt.autonomous_cost_cents)}
                            </title>
                            {autoH > 0 && (
                              <rect
                                x={x}
                                y={130 - totalH}
                                width={barWidth}
                                height={autoH}
                                rx={1.5}
                                className="fill-sky-400/85"
                              />
                            )}
                            {prH > 0 && (
                              <rect
                                x={x}
                                y={130 - prH}
                                width={barWidth}
                                height={prH}
                                rx={1.5}
                                className="fill-emerald-400"
                              />
                            )}
                          </g>
                        );
                      })}
                    </svg>
                    <div className="flex items-center gap-4 text-[11px] text-muted-foreground font-mono">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2.5 w-2.5 rounded-sm bg-emerald-400" />
                        PR Review
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-2.5 w-2.5 rounded-sm bg-sky-400" />
                        Forge + Reviewer
                      </span>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Daily Turnaround Trend Line Chart */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Daily p50 Turnaround Trend
                </CardTitle>
                <CardDescription className="text-xs">
                  Median duration per UTC day for completed PR reviews and
                  tasks.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!hasAnyLatency ? (
                  <div className="h-44 flex flex-col items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
                    <span>
                      No completed reviews or task runs in this {days} day
                      window.
                    </span>
                    <span className="text-[11px] mt-1">
                      Completed runs will chart daily median turnaround here.
                    </span>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <svg
                      viewBox="0 0 560 150"
                      role="img"
                      aria-label="Daily p50 turnaround line chart"
                      className="w-full h-44 overflow-visible"
                    >
                      <line
                        x1="16"
                        y1="130"
                        x2="544"
                        y2="130"
                        stroke="currentColor"
                        className="text-border"
                        strokeWidth="1"
                      />
                      <polyline
                        fill="none"
                        stroke="currentColor"
                        className="text-emerald-400"
                        strokeWidth="2"
                        points={prPoints}
                      />
                      <polyline
                        fill="none"
                        stroke="currentColor"
                        className="text-sky-400"
                        strokeWidth="2"
                        strokeDasharray="4 2"
                        points={taskPoints}
                      />
                    </svg>
                    <div className="flex items-center gap-4 text-[11px] text-muted-foreground font-mono">
                      <span className="flex items-center gap-1.5">
                        <span className="h-0.5 w-4 bg-emerald-400" />
                        PR Review p50
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-0.5 w-4 bg-sky-400" />
                        Task Active p50
                      </span>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Severity & Category Breakdown + Top Rules */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Findings by Severity</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2.5 text-xs">
                {(["critical", "major", "minor", "info"] as const).map(
                  (sev) => {
                    const count = data.findings_by_severity[sev] ?? 0;
                    const pct = Math.round((count / totalFindings) * 100);
                    return (
                      <div key={sev} className="space-y-1">
                        <div className="flex justify-between font-mono">
                          <span className="capitalize text-foreground">
                            {sev}
                          </span>
                          <span className="text-muted-foreground">{count}</span>
                        </div>
                        <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                          <div
                            className="h-full bg-emerald-500 transition-all"
                            style={{
                              width: `${count > 0 ? Math.max(4, pct) : 0}%`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  }
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Findings by Category</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2.5 text-xs">
                {(
                  [
                    "security",
                    "bug",
                    "performance",
                    "architecture",
                    "style",
                  ] as const
                ).map((cat) => {
                  const count = data.findings_by_category[cat] ?? 0;
                  const pct = Math.round((count / totalFindings) * 100);
                  return (
                    <div key={cat} className="space-y-1">
                      <div className="flex justify-between font-mono">
                        <span className="capitalize text-foreground">
                          {cat}
                        </span>
                        <span className="text-muted-foreground">{count}</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                        <div
                          className="h-full bg-sky-500 transition-all"
                          style={{
                            width: `${count > 0 ? Math.max(4, pct) : 0}%`,
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>

            <Card className="lg:col-span-1">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                  Top Custom Rules
                </CardTitle>
                <CardDescription className="text-xs">
                  Most triggered active rules and developer feedback counts.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {data.top_rules.length === 0 ? (
                  <div className="py-6 text-center text-xs text-muted-foreground">
                    No rule-linked findings recorded in this window.
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Rule</TableHead>
                        <TableHead className="text-xs text-right">
                          Hits
                        </TableHead>
                        <TableHead className="text-xs text-right">
                          Acc / Dis
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.top_rules.map((rule) => (
                        <TableRow key={rule.rule_id}>
                          <TableCell className="text-xs">
                            <div className="font-medium text-foreground truncate max-w-[160px]">
                              {rule.title}
                            </div>
                            <Badge
                              variant="outline"
                              className={cn(
                                "mt-1 text-[10px]",
                                severityToneClass(rule.severity)
                              )}
                            >
                              {rule.severity}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-right font-mono">
                            {rule.triggered_count}
                          </TableCell>
                          <TableCell className="text-xs text-right font-mono text-muted-foreground">
                            {rule.accepted_count} / {rule.dismissed_count}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
