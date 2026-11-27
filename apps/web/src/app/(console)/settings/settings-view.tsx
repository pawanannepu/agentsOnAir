"use client";

import * as React from "react";
import Link from "next/link";
import {
  Cpu,
  Shield,
  Save,
  ShieldAlert,
  ArrowLeft,
  Loader2,
  DollarSign,
  Network,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";
import { toast } from "@/components/ui/sonner";
import {
  dispatchOrgForbiddenEvent,
  extractOrgForbiddenDetail,
} from "@/lib/org-recovery";

export interface SettingsViewProps {
  canPersistToApi?: boolean;
  getToken?: () => Promise<string | null>;
}

const RISK_CATEGORY_LABELS: Array<{
  id: string;
  label: string;
  description: string;
}> = [
  {
    id: "destructive_shell",
    label: "Destructive Shell Commands",
    description: "rm -rf, mkfs, dd, chmod 777, hard resets",
  },
  {
    id: "external_network",
    label: "External Network Tools",
    description: "curl, wget, nc, ssh, scp invocations",
  },
  {
    id: "sensitive_path_edit",
    label: "Sensitive Path Edits",
    description: ".github/workflows/**, .env*, **/auth/**",
  },
  {
    id: "force_git_op",
    label: "Force Git Operations",
    description: "git push --force, rebase, reset --hard",
  },
  {
    id: "large_diff",
    label: "Large Diff Threshold",
    description: "PR diffs exceeding configured line cap",
  },
];

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function SettingsView({
  canPersistToApi = false,
  getToken,
}: SettingsViewProps) {
  const [provider, setProvider] = React.useState("e2b");
  const [timeoutMinutes, setTimeoutMinutes] = React.useState("10");
  const [protectedBranches, setProtectedBranches] = React.useState(
    "main, master, release/*"
  );
  const [requireApprovalFor, setRequireApprovalFor] = React.useState<string[]>([
    "destructive_shell",
    "external_network",
    "sensitive_path_edit",
    "force_git_op",
    "large_diff",
  ]);
  const [maxTaskCostCents, setMaxTaskCostCents] = React.useState("500");
  const [maxMonthlyOrgCostCents, setMaxMonthlyOrgCostCents] =
    React.useState("10000");
  const [maxCycles, setMaxCycles] = React.useState("3");
  const [networkEgressMode, setNetworkEgressMode] =
    React.useState("off_after_install");
  const [allowedEgressDomains, setAllowedEgressDomains] = React.useState("");
  const [largeDiffLinesThreshold, setLargeDiffLinesThreshold] =
    React.useState("500");
  const [usage, setUsage] = React.useState<{
    billing_month: string;
    total_tokens: number;
    total_cost_cents: number;
    max_monthly_org_cost_cents: number;
    remaining_cents: number;
  } | null>(null);
  const [isSaving, setIsSaving] = React.useState(false);

  useBreadcrumbs([{ label: "Settings" }]);

  React.useEffect(() => {
    if (!canPersistToApi) {
      return;
    }
    let active = true;
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    const loadSettingsAndUsage = async () => {
      try {
        const token = getToken
          ? await getToken()
          : typeof window !== "undefined" && window.Clerk?.session?.getToken
            ? await window.Clerk.session.getToken()
            : null;
        if (!token) {
          return;
        }
        const headers = { Authorization: `Bearer ${token}` };

        const [settingsRes, guardrailsRes, usageRes] = await Promise.all([
          fetch(`${baseUrl}/api/v1/organizations/settings`, { headers }),
          fetch(`${baseUrl}/api/v1/organizations/guardrails`, { headers }),
          fetch(`${baseUrl}/api/v1/organizations/usage`, { headers }),
        ]);

        if (settingsRes.status === 403) {
          const detail = extractOrgForbiddenDetail(
            await settingsRes.json().catch(() => null)
          );
          if (detail) {
            dispatchOrgForbiddenEvent(detail);
          }
          return;
        }

        if (settingsRes.ok && active) {
          const data = (await settingsRes.json()) as {
            settings?: Record<string, unknown>;
          };
          if (data.settings) {
            if (
              data.settings.sandbox_provider === "e2b" ||
              data.settings.sandbox_provider === "docker"
            ) {
              setProvider(data.settings.sandbox_provider);
            }
            if (typeof data.settings.timeout_minutes === "number") {
              setTimeoutMinutes(String(data.settings.timeout_minutes));
            }
          }
        }

        if (guardrailsRes.ok && active) {
          const g = (await guardrailsRes.json()) as {
            protected_branches?: string[];
            require_approval_for?: string[];
            max_task_cost_cents?: number;
            max_monthly_org_cost_cents?: number;
            timeout_minutes?: number;
            max_cycles?: number;
            network_egress_mode?: string;
            allowed_egress_domains?: string[];
            large_diff_lines_threshold?: number;
          };
          if (Array.isArray(g.protected_branches)) {
            setProtectedBranches(g.protected_branches.join(", "));
          }
          if (Array.isArray(g.require_approval_for)) {
            setRequireApprovalFor(g.require_approval_for);
          }
          if (typeof g.max_task_cost_cents === "number") {
            setMaxTaskCostCents(String(g.max_task_cost_cents));
          }
          if (typeof g.max_monthly_org_cost_cents === "number") {
            setMaxMonthlyOrgCostCents(String(g.max_monthly_org_cost_cents));
          }
          if (typeof g.timeout_minutes === "number") {
            setTimeoutMinutes(String(g.timeout_minutes));
          }
          if (typeof g.max_cycles === "number") {
            setMaxCycles(String(g.max_cycles));
          }
          if (typeof g.network_egress_mode === "string") {
            setNetworkEgressMode(g.network_egress_mode);
          }
          if (Array.isArray(g.allowed_egress_domains)) {
            setAllowedEgressDomains(g.allowed_egress_domains.join(", "));
          }
          if (typeof g.large_diff_lines_threshold === "number") {
            setLargeDiffLinesThreshold(String(g.large_diff_lines_threshold));
          }
        }

        if (usageRes.ok && active) {
          const u = (await usageRes.json()) as {
            billing_month: string;
            total_tokens: number;
            total_cost_cents: number;
            max_monthly_org_cost_cents: number;
            remaining_cents: number;
          };
          setUsage(u);
        }
      } catch {
        // Keep defaults if engine is offline during preview
      }
    };

    void loadSettingsAndUsage();
    return () => {
      active = false;
    };
  }, [canPersistToApi, getToken]);

  const toggleRiskCategory = (category: string) => {
    setRequireApprovalFor((prev) =>
      prev.includes(category)
        ? prev.filter((item) => item !== category)
        : [...prev, category]
    );
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!canPersistToApi) {
      toast.success("Workspace configuration saved successfully.");
      return;
    }

    const parsedBranches = protectedBranches
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const parsedDomains = allowedEgressDomains
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    setIsSaving(true);
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    try {
      const token = getToken
        ? await getToken()
        : typeof window !== "undefined" && window.Clerk?.session?.getToken
          ? await window.Clerk.session.getToken()
          : null;

      const res = await fetch(`${baseUrl}/api/v1/organizations/settings`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          sandbox_provider: provider,
          timeout_minutes: Number(timeoutMinutes),
          protected_branches: parsedBranches,
          require_approval_for: requireApprovalFor,
          max_task_cost_cents: Number(maxTaskCostCents),
          max_monthly_org_cost_cents: Number(maxMonthlyOrgCostCents),
          max_cycles: Number(maxCycles),
          network_egress_mode: networkEgressMode,
          allowed_egress_domains: parsedDomains,
          large_diff_lines_threshold: Number(largeDiffLinesThreshold),
        }),
      });

      if (res.status === 403) {
        const payload = (await res.json().catch(() => null)) as {
          detail?: { code?: string; message?: string };
        } | null;
        const forbiddenDetail = extractOrgForbiddenDetail(payload);
        if (forbiddenDetail) {
          dispatchOrgForbiddenEvent(forbiddenDetail);
        }
        toast.error(
          payload?.detail?.message ||
            "Admin permission (org:admin) is required to save settings."
        );
        return;
      }

      if (!res.ok) {
        toast.error("Failed to save workspace configuration.");
        return;
      }

      toast.success("Workspace configuration saved successfully.");
    } catch {
      toast.error("Unable to reach agent engine to save configuration.");
    } finally {
      setIsSaving(false);
    }
  };

  const monthlyCap =
    usage?.max_monthly_org_cost_cents ??
    Math.max(1, Number(maxMonthlyOrgCostCents) || 10000);
  const monthlyUsed = usage?.total_cost_cents ?? 0;
  const spendPct = Math.min(100, Math.round((monthlyUsed / monthlyCap) * 100));

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Workspace Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Configure execution sandboxes, branch protection, spending caps, and
          security policies for this organization.
        </p>
      </div>

      {/* Monthly Organization Spend Meter */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-emerald-400" />
            Monthly Organization Spend ({usage?.billing_month ?? "Current UTC"})
          </CardTitle>
          <CardDescription className="text-xs">
            Real time aggregated LLM spend across autonomous tasks and pull
            request reviews.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          <div className="flex items-center justify-between font-mono">
            <span className="text-foreground font-medium">
              {formatCents(monthlyUsed)} spent of {formatCents(monthlyCap)} cap
            </span>
            <span className="text-muted-foreground">
              {(usage?.total_tokens ?? 0).toLocaleString()} tokens ·{" "}
              {formatCents(Math.max(0, monthlyCap - monthlyUsed))} remaining
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Monthly organization spend"
            aria-valuemin={0}
            aria-valuemax={monthlyCap}
            aria-valuenow={monthlyUsed}
            className="h-2.5 w-full rounded-full bg-secondary overflow-hidden"
          >
            <div
              className={
                spendPct >= 90
                  ? "h-full bg-destructive transition-all"
                  : spendPct >= 70
                    ? "h-full bg-amber-500 transition-all"
                    : "h-full bg-emerald-500 transition-all"
              }
              style={{ width: `${spendPct}%` }}
            />
          </div>
        </CardContent>
      </Card>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Sandbox Execution Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Cpu className="h-4 w-4 text-emerald-400" />
              Sandbox Execution Provider
            </CardTitle>
            <CardDescription className="text-xs">
              Select the compute environment and active runtime limits for
              untrusted agent code.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label
                htmlFor="sandbox-provider-select"
                className="text-xs font-medium text-foreground"
              >
                Primary Execution Runtime
              </label>
              <Select value={provider} onValueChange={setProvider}>
                <SelectTrigger
                  id="sandbox-provider-select"
                  className="w-full sm:w-80"
                >
                  <SelectValue placeholder="Select sandbox runtime" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="e2b">
                    E2B Firecracker microVM (Recommended)
                  </SelectItem>
                  <SelectItem value="docker">
                    Local Docker Engine (Fallback)
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[11px] text-muted-foreground">
                E2B creates isolated hardware virtual machines with dedicated
                kernel and memory boundaries.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
              <div className="space-y-2">
                <label
                  htmlFor="timeout-minutes"
                  className="text-xs font-medium text-foreground"
                >
                  Task Execution Timeout (Minutes)
                </label>
                <Input
                  id="timeout-minutes"
                  type="number"
                  min="1"
                  max="60"
                  value={timeoutMinutes}
                  onChange={(e) => setTimeoutMinutes(e.target.value)}
                  className="w-full sm:w-40 font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  Active execution budget (1 to 60 minutes, excluding approval
                  pauses).
                </p>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="max-cycles"
                  className="text-xs font-medium text-foreground"
                >
                  Max Review Cycles
                </label>
                <Input
                  id="max-cycles"
                  type="number"
                  min="1"
                  max="10"
                  value={maxCycles}
                  onChange={(e) => setMaxCycles(e.target.value)}
                  className="w-full sm:w-40 font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  Maximum Forge and Reviewer fix cycles per task (1 to 10).
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Budget Limits & Egress Isolation */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Network className="h-4 w-4 text-blue-400" />
              Budgets & Network Egress
            </CardTitle>
            <CardDescription className="text-xs">
              Configure integer cent spending caps and outbound sandbox network
              isolation.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="space-y-2">
                <label
                  htmlFor="max-task-cost-cents"
                  className="text-xs font-medium text-foreground"
                >
                  Max Task Cost (Cents)
                </label>
                <Input
                  id="max-task-cost-cents"
                  type="number"
                  min="1"
                  value={maxTaskCostCents}
                  onChange={(e) => setMaxTaskCostCents(e.target.value)}
                  className="font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  {formatCents(Number(maxTaskCostCents) || 0)} per task run
                </p>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="max-monthly-cost-cents"
                  className="text-xs font-medium text-foreground"
                >
                  Max Monthly Org Cost (Cents)
                </label>
                <Input
                  id="max-monthly-cost-cents"
                  type="number"
                  min="1"
                  value={maxMonthlyOrgCostCents}
                  onChange={(e) => setMaxMonthlyOrgCostCents(e.target.value)}
                  className="font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  {formatCents(Number(maxMonthlyOrgCostCents) || 0)} monthly cap
                </p>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="large-diff-threshold"
                  className="text-xs font-medium text-foreground"
                >
                  Large Diff Threshold (Lines)
                </label>
                <Input
                  id="large-diff-threshold"
                  type="number"
                  min="1"
                  value={largeDiffLinesThreshold}
                  onChange={(e) => setLargeDiffLinesThreshold(e.target.value)}
                  className="font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  Added + removed diff lines requiring approval
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
              <div className="space-y-2">
                <label
                  htmlFor="network-egress-select"
                  className="text-xs font-medium text-foreground"
                >
                  Sandbox Network Egress Mode
                </label>
                <Select
                  value={networkEgressMode}
                  onValueChange={setNetworkEgressMode}
                >
                  <SelectTrigger id="network-egress-select">
                    <SelectValue placeholder="Select egress mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="off_after_install">
                      Off After Install (Recommended)
                    </SelectItem>
                    <SelectItem value="allowlist">
                      Domain Allowlist Only
                    </SelectItem>
                    <SelectItem value="unrestricted">Unrestricted</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="allowed-egress-domains"
                  className="text-xs font-medium text-foreground"
                >
                  Allowed Egress Domains (comma separated)
                </label>
                <Input
                  id="allowed-egress-domains"
                  value={allowedEgressDomains}
                  onChange={(e) => setAllowedEgressDomains(e.target.value)}
                  placeholder="registry.npmjs.org, *.pypi.org"
                  className="font-mono text-xs"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Security and Approval Rules */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="h-4 w-4 text-purple-400" />
              Guardrails & Tenant Isolation
            </CardTitle>
            <CardDescription className="text-xs">
              Protected branch enforcement, risky action approval gates, and
              audit immutability.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            <div className="space-y-2">
              <label
                htmlFor="protected-branches-input"
                className="text-xs font-medium text-foreground"
              >
                Protected Branch Patterns (comma separated globs)
              </label>
              <Input
                id="protected-branches-input"
                value={protectedBranches}
                onChange={(e) => setProtectedBranches(e.target.value)}
                placeholder="main, master, release/*"
                className="font-mono text-xs"
              />
            </div>

            <fieldset className="space-y-2">
              <legend className="text-xs font-medium text-foreground mb-1">
                Require Human Approval For
              </legend>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {RISK_CATEGORY_LABELS.map((item) => {
                  const checked = requireApprovalFor.includes(item.id);
                  return (
                    <label
                      key={item.id}
                      className="flex items-start gap-2.5 rounded-md border border-border p-2.5 cursor-pointer hover:bg-accent/40"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleRiskCategory(item.id)}
                        className="mt-0.5 h-4 w-4 rounded border-border accent-emerald-500"
                      />
                      <div>
                        <div className="font-medium text-foreground">
                          {item.label}
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          {item.description}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <div className="flex items-center justify-between py-2 border-t border-border/50">
              <div>
                <div className="font-medium text-foreground">
                  Protected Branch Guard
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Prevent autonomous agents from pushing directly to protected
                  branches.
                </div>
              </div>
              <span className="text-emerald-400 font-medium font-mono text-[11px]">
                Enforced
              </span>
            </div>

            <div className="flex items-center justify-between py-2">
              <div>
                <div className="font-medium text-foreground">
                  Database Trigger Immutability
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Audit log records are append only and protected from
                  alteration or deletion.
                </div>
              </div>
              <span className="text-emerald-400 font-medium font-mono text-[11px]">
                Active
              </span>
            </div>
          </CardContent>
          <CardFooter className="pt-2 border-t border-border flex justify-end">
            <Button
              type="submit"
              size="sm"
              disabled={isSaving}
              className="gap-1.5"
            >
              {isSaving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              <span>Save Changes</span>
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}

export function SettingsUnauthorizedView() {
  useBreadcrumbs([{ label: "Settings" }]);

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Workspace Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Organization administrator permissions are required for this view.
        </p>
      </div>

      <Card className="border-amber-500/40 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2 text-amber-400">
            <ShieldAlert className="h-4 w-4" />
            Admin Access Required
          </CardTitle>
          <CardDescription className="text-xs">
            Only members with the <code className="font-mono">org:admin</code>{" "}
            role can view or update sandbox runtime settings and organization
            guardrails.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          Ask an administrator in your Clerk organization to update your role or
          switch to an organization where you hold admin permissions.
        </CardContent>
        <CardFooter className="border-t border-border pt-4">
          <Button asChild variant="outline" size="sm" className="gap-1.5">
            <Link href="/tasks">
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>Back to Agent Tasks</span>
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
