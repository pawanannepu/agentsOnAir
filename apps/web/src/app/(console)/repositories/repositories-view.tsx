"use client";

import * as React from "react";
import {
  FolderGit2,
  PlusCircle,
  ExternalLink,
  GitBranch,
  Lock,
  Globe,
  ShieldCheck,
  Loader2,
  RotateCcw,
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
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

export interface GuardrailPolicyDto {
  protected_branches: string[];
  protected_branch_guard: boolean;
  require_approval_for: string[];
  max_task_cost_cents: number;
  max_monthly_org_cost_cents: number;
  timeout_minutes: number;
  max_cycles: number;
  network_egress_mode: string;
  allowed_egress_domains: string[];
  large_diff_lines_threshold: number;
}

interface RepositoryItem {
  id: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  isPrivate: boolean;
  activeTasks: number;
  lastSynced: string;
  effectivePolicy?: GuardrailPolicyDto;
}

export interface RepositoriesViewProps {
  canLoadFromApi?: boolean;
  isAdmin?: boolean;
  getToken?: () => Promise<string | null>;
}

const mockRepositories: RepositoryItem[] = [
  {
    id: "repo_01",
    name: "core",
    fullName: "agentsOnAir/core",
    defaultBranch: "main",
    isPrivate: true,
    activeTasks: 1,
    lastSynced: "2 minutes ago",
  },
  {
    id: "repo_02",
    name: "web-platform",
    fullName: "acme/web-platform",
    defaultBranch: "main",
    isPrivate: true,
    activeTasks: 1,
    lastSynced: "1 hour ago",
  },
  {
    id: "repo_03",
    name: "sandbox-templates",
    fullName: "agentsOnAir/sandbox-templates",
    defaultBranch: "main",
    isPrivate: false,
    activeTasks: 0,
    lastSynced: "Yesterday",
  },
];

export function RepositoriesView({
  canLoadFromApi = false,
  isAdmin = false,
  getToken,
}: RepositoriesViewProps) {
  useBreadcrumbs([{ label: "Repositories" }]);

  const [repositories, setRepositories] = React.useState<RepositoryItem[]>(
    canLoadFromApi ? [] : mockRepositories
  );
  const [isLoading, setIsLoading] = React.useState(canLoadFromApi);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const [selectedRepo, setSelectedRepo] = React.useState<RepositoryItem | null>(
    null
  );
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [orgDefaults, setOrgDefaults] =
    React.useState<GuardrailPolicyDto | null>(null);
  const [repoOverrides, setRepoOverrides] = React.useState<
    Record<string, unknown>
  >({});
  const [effectivePolicy, setEffectivePolicy] =
    React.useState<GuardrailPolicyDto | null>(null);

  const [overrideBranches, setOverrideBranches] = React.useState("");
  const [overrideMaxTaskCost, setOverrideMaxTaskCost] = React.useState("");
  const [overrideTimeout, setOverrideTimeout] = React.useState("");
  const [overrideMaxCycles, setOverrideMaxCycles] = React.useState("");
  const [overrideEgressMode, setOverrideEgressMode] = React.useState("inherit");
  const [overrideLargeDiff, setOverrideLargeDiff] = React.useState("");
  const [isDrawerLoading, setIsDrawerLoading] = React.useState(false);
  const [isSavingOverride, setIsSavingOverride] = React.useState(false);

  const resolveToken = React.useCallback(async (): Promise<string | null> => {
    if (getToken) {
      return await getToken();
    }
    if (typeof window !== "undefined" && window.Clerk?.session?.getToken) {
      return await window.Clerk.session.getToken();
    }
    return null;
  }, [getToken]);

  React.useEffect(() => {
    if (!canLoadFromApi) {
      return;
    }
    let active = true;
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    const loadRepositories = async () => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const token = await resolveToken();
        const res = await fetch(`${baseUrl}/api/v1/repositories`, {
          credentials: "include",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (res.status === 403 && active) {
          const detail = extractOrgForbiddenDetail(
            await res.json().catch(() => null)
          );
          if (detail) dispatchOrgForbiddenEvent(detail);
          setLoadError("Organization access denied.");
          return;
        }
        if (!res.ok) {
          if (active)
            setLoadError(`Failed to load repositories (${res.status}).`);
          return;
        }
        const data = (await res.json()) as {
          items?: Array<{
            id: string;
            name: string;
            full_name: string;
            default_branch: string;
            is_private: boolean;
            effective_policy?: GuardrailPolicyDto;
          }>;
        };
        if (active) {
          const mapped: RepositoryItem[] = (data.items ?? []).map((item) => ({
            id: item.id,
            name: item.name,
            fullName: item.full_name,
            defaultBranch: item.default_branch,
            isPrivate: item.is_private,
            activeTasks: 0,
            lastSynced: "Synced",
            effectivePolicy: item.effective_policy,
          }));
          setRepositories(mapped);
        }
      } catch {
        if (active) {
          setLoadError("Unable to reach agent engine to load repositories.");
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };

    void loadRepositories();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, resolveToken]);

  const openGuardrailsDrawer = async (repo: RepositoryItem) => {
    setSelectedRepo(repo);
    setDrawerOpen(true);
    setOverrideBranches("");
    setOverrideMaxTaskCost("");
    setOverrideTimeout("");
    setOverrideMaxCycles("");
    setOverrideEgressMode("inherit");
    setOverrideLargeDiff("");

    if (!canLoadFromApi) {
      return;
    }

    setIsDrawerLoading(true);
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";
    try {
      const token = await resolveToken();
      const res = await fetch(
        `${baseUrl}/api/v1/repositories/${repo.id}/guardrails`,
        {
          credentials: "include",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        }
      );
      if (res.ok) {
        const data = (await res.json()) as {
          org_defaults: GuardrailPolicyDto;
          repo_overrides: Record<string, unknown>;
          effective_policy: GuardrailPolicyDto;
        };
        setOrgDefaults(data.org_defaults);
        setRepoOverrides(data.repo_overrides || {});
        setEffectivePolicy(data.effective_policy);

        const ov = data.repo_overrides || {};
        if (Array.isArray(ov.protected_branches)) {
          setOverrideBranches(ov.protected_branches.join(", "));
        }
        if (typeof ov.max_task_cost_cents === "number") {
          setOverrideMaxTaskCost(String(ov.max_task_cost_cents));
        }
        if (typeof ov.timeout_minutes === "number") {
          setOverrideTimeout(String(ov.timeout_minutes));
        }
        if (typeof ov.max_cycles === "number") {
          setOverrideMaxCycles(String(ov.max_cycles));
        }
        if (typeof ov.network_egress_mode === "string") {
          setOverrideEgressMode(ov.network_egress_mode);
        }
        if (typeof ov.large_diff_lines_threshold === "number") {
          setOverrideLargeDiff(String(ov.large_diff_lines_threshold));
        }
      }
    } catch {
      toast.error("Unable to load repository guardrail overrides.");
    } finally {
      setIsDrawerLoading(false);
    }
  };

  const handleSaveOverrides = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRepo || !canLoadFromApi) {
      setDrawerOpen(false);
      return;
    }

    setIsSavingOverride(true);
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    const payload: Record<string, unknown> = {
      protected_branches: overrideBranches.trim()
        ? overrideBranches
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : null,
      max_task_cost_cents: overrideMaxTaskCost.trim()
        ? Number(overrideMaxTaskCost)
        : null,
      timeout_minutes: overrideTimeout.trim() ? Number(overrideTimeout) : null,
      max_cycles: overrideMaxCycles.trim() ? Number(overrideMaxCycles) : null,
      network_egress_mode:
        overrideEgressMode === "inherit" ? null : overrideEgressMode,
      large_diff_lines_threshold: overrideLargeDiff.trim()
        ? Number(overrideLargeDiff)
        : null,
    };

    try {
      const token = await resolveToken();
      const res = await fetch(
        `${baseUrl}/api/v1/repositories/${selectedRepo.id}/guardrails`,
        {
          method: "PATCH",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(payload),
        }
      );

      if (res.status === 403) {
        const errPayload = (await res.json().catch(() => null)) as {
          detail?: { code?: string; message?: string };
        } | null;
        const detail = extractOrgForbiddenDetail(errPayload);
        if (detail) dispatchOrgForbiddenEvent(detail);
        toast.error(
          errPayload?.detail?.message ||
            "Only org:admin members can update repository overrides."
        );
        return;
      }

      if (!res.ok) {
        toast.error("Failed to save repository guardrail overrides.");
        return;
      }

      const data = (await res.json()) as {
        repo_overrides: Record<string, unknown>;
        effective_policy: GuardrailPolicyDto;
      };
      setRepoOverrides(data.repo_overrides);
      setEffectivePolicy(data.effective_policy);
      setRepositories((prev) =>
        prev.map((r) =>
          r.id === selectedRepo.id
            ? { ...r, effectivePolicy: data.effective_policy }
            : r
        )
      );
      toast.success("Repository guardrail overrides saved.");
      setDrawerOpen(false);
    } catch {
      toast.error("Unable to reach agent engine.");
    } finally {
      setIsSavingOverride(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Connected Repositories
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Repositories authorized via the agentsOnAir GitHub App for automated
            task runs, guardrail overrides, and code reviews.
          </p>
        </div>
        <Button size="sm" className="gap-1.5 shrink-0">
          <PlusCircle className="h-4 w-4" />
          <span>Connect Repository</span>
        </Button>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((k) => (
            <div
              key={k}
              className="h-56 rounded-xl border border-border bg-card animate-pulse"
            />
          ))}
        </div>
      )}

      {!isLoading && loadError && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="py-6 text-xs text-destructive">
            {loadError}
          </CardContent>
        </Card>
      )}

      {!isLoading && !loadError && repositories.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No repositories connected yet. Install the agentsOnAir GitHub App on
            your organization to synchronize repositories.
          </CardContent>
        </Card>
      )}

      {/* Repositories Grid */}
      {!isLoading && !loadError && repositories.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {repositories.map((repo) => (
            <Card key={repo.id} className="flex flex-col justify-between">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FolderGit2 className="h-4 w-4 text-blue-400 shrink-0" />
                    <CardTitle className="text-base truncate">
                      {repo.name}
                    </CardTitle>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {repo.isPrivate ? (
                      <span className="flex items-center gap-1 text-[11px] text-zinc-400 font-mono px-2 py-0.5 rounded bg-zinc-800">
                        <Lock className="h-3 w-3" />
                        Private
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] text-zinc-400 font-mono px-2 py-0.5 rounded bg-zinc-800">
                        <Globe className="h-3 w-3" />
                        Public
                      </span>
                    )}
                  </div>
                </div>
                <CardDescription className="text-xs font-mono">
                  {repo.fullName}
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-border/50">
                  <span className="text-muted-foreground flex items-center gap-1">
                    <GitBranch className="h-3.5 w-3.5" />
                    Default Branch
                  </span>
                  <span className="font-mono font-medium text-foreground">
                    {repo.defaultBranch}
                  </span>
                </div>
                <div className="flex justify-between py-1 border-b border-border/50">
                  <span className="text-muted-foreground">Active Tasks</span>
                  <span className="font-mono font-medium">
                    {repo.activeTasks > 0 ? (
                      <Badge variant="running" pulse>
                        {repo.activeTasks} active
                      </Badge>
                    ) : (
                      <span className="text-zinc-500">Idle</span>
                    )}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-muted-foreground">
                    {repo.effectivePolicy ? "Task Cost Cap" : "Last Sync"}
                  </span>
                  <span className="text-muted-foreground font-mono">
                    {repo.effectivePolicy
                      ? `$${(repo.effectivePolicy.max_task_cost_cents / 100).toFixed(2)}`
                      : repo.lastSynced}
                  </span>
                </div>
              </CardContent>

              <CardFooter className="pt-2 border-t border-border/50 flex gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="flex-1 text-xs gap-1.5"
                  onClick={() => void openGuardrailsDrawer(repo)}
                >
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <span>Guardrails</span>
                </Button>
                <Button asChild variant="outline" size="sm" className="text-xs">
                  <a
                    href={`https://github.com/${repo.fullName}`}
                    target="_blank"
                    rel="noreferrer"
                    className="gap-1.5"
                  >
                    <span>GitHub</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {/* Repository Guardrail Overrides Drawer / Dialog */}
      <Dialog open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Guardrail Overrides · {selectedRepo?.fullName}
            </DialogTitle>
            <DialogDescription className="text-xs">
              Leave any field empty to inherit the organization default.{" "}
              {!isAdmin &&
                "Read only view: org:admin role is required to modify overrides."}
            </DialogDescription>
          </DialogHeader>

          {isDrawerLoading ? (
            <div className="py-8 flex items-center justify-center text-xs text-muted-foreground gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Loading effective guardrails...</span>
            </div>
          ) : (
            <form onSubmit={handleSaveOverrides} className="space-y-4 text-xs">
              <div className="space-y-1.5">
                <label
                  htmlFor="repo-protected-branches"
                  className="font-medium text-foreground"
                >
                  Protected Branches Override
                </label>
                <Input
                  id="repo-protected-branches"
                  value={overrideBranches}
                  onChange={(e) => setOverrideBranches(e.target.value)}
                  disabled={!isAdmin}
                  placeholder={`Inherit (${orgDefaults?.protected_branches.join(", ") ?? "main, master, release/*"})`}
                  className="font-mono text-xs"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label
                    htmlFor="repo-max-task-cost"
                    className="font-medium text-foreground"
                  >
                    Max Task Cost (Cents)
                  </label>
                  <Input
                    id="repo-max-task-cost"
                    type="number"
                    min="1"
                    value={overrideMaxTaskCost}
                    onChange={(e) => setOverrideMaxTaskCost(e.target.value)}
                    disabled={!isAdmin}
                    placeholder={`Inherit (${orgDefaults?.max_task_cost_cents ?? 500})`}
                    className="font-mono text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="repo-timeout-minutes"
                    className="font-medium text-foreground"
                  >
                    Timeout (Minutes)
                  </label>
                  <Input
                    id="repo-timeout-minutes"
                    type="number"
                    min="1"
                    max="60"
                    value={overrideTimeout}
                    onChange={(e) => setOverrideTimeout(e.target.value)}
                    disabled={!isAdmin}
                    placeholder={`Inherit (${orgDefaults?.timeout_minutes ?? 10})`}
                    className="font-mono text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="repo-max-cycles"
                    className="font-medium text-foreground"
                  >
                    Max Review Cycles
                  </label>
                  <Input
                    id="repo-max-cycles"
                    type="number"
                    min="1"
                    max="10"
                    value={overrideMaxCycles}
                    onChange={(e) => setOverrideMaxCycles(e.target.value)}
                    disabled={!isAdmin}
                    placeholder={`Inherit (${orgDefaults?.max_cycles ?? 3})`}
                    className="font-mono text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="repo-large-diff"
                    className="font-medium text-foreground"
                  >
                    Large Diff Threshold (Lines)
                  </label>
                  <Input
                    id="repo-large-diff"
                    type="number"
                    min="1"
                    value={overrideLargeDiff}
                    onChange={(e) => setOverrideLargeDiff(e.target.value)}
                    disabled={!isAdmin}
                    placeholder={`Inherit (${orgDefaults?.large_diff_lines_threshold ?? 500})`}
                    className="font-mono text-xs"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="repo-egress-mode"
                  className="font-medium text-foreground"
                >
                  Network Egress Mode
                </label>
                <Select
                  value={overrideEgressMode}
                  onValueChange={setOverrideEgressMode}
                  disabled={!isAdmin}
                >
                  <SelectTrigger id="repo-egress-mode">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inherit">
                      Inherit org default (
                      {orgDefaults?.network_egress_mode ?? "off_after_install"})
                    </SelectItem>
                    <SelectItem value="off_after_install">
                      Off After Install
                    </SelectItem>
                    <SelectItem value="allowlist">Allowlist</SelectItem>
                    <SelectItem value="unrestricted">Unrestricted</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {effectivePolicy && (
                <div className="rounded-lg border border-border bg-secondary/40 p-3 space-y-1 text-[11px] font-mono">
                  <div className="font-semibold text-foreground">
                    Effective Merged Policy ({Object.keys(repoOverrides).length}{" "}
                    overrides)
                  </div>
                  <div className="text-muted-foreground">
                    Branches: {effectivePolicy.protected_branches.join(", ")} ·
                    Cap: $
                    {(effectivePolicy.max_task_cost_cents / 100).toFixed(2)} ·
                    Timeout: {effectivePolicy.timeout_minutes}m · Egress:{" "}
                    {effectivePolicy.network_egress_mode}
                  </div>
                </div>
              )}

              <DialogFooter className="gap-2 pt-2">
                {isAdmin && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setOverrideBranches("");
                      setOverrideMaxTaskCost("");
                      setOverrideTimeout("");
                      setOverrideMaxCycles("");
                      setOverrideEgressMode("inherit");
                      setOverrideLargeDiff("");
                    }}
                    className="gap-1.5"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    <span>Clear Overrides</span>
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setDrawerOpen(false)}
                >
                  Close
                </Button>
                {isAdmin && (
                  <Button
                    type="submit"
                    size="sm"
                    disabled={isSavingOverride}
                    className="gap-1.5"
                  >
                    {isSavingOverride && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    )}
                    <span>Save Overrides</span>
                  </Button>
                )}
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
