"use client";

import * as React from "react";
import {
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  RotateCcw,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/sonner";
import {
  agentFetchJson,
  resolveClientAuthToken,
  severityToneClass,
  type EffectiveReviewRuleDto,
  type LearnedPreferenceDto,
  type ReviewExampleDto,
  type ReviewRuleDto,
  type RuleCategory,
  type RuleSeverity,
} from "@/lib/review-api";
import { cn } from "@/lib/utils";

interface RepoTabBaseProps {
  repoId: string;
  canLoadFromApi: boolean;
  isAdmin: boolean;
  getToken?: () => Promise<string | null>;
}

export function RepoRulesAndOverridesTab({
  repoId,
  canLoadFromApi,
  isAdmin,
  getToken,
}: RepoTabBaseProps) {
  const [rules, setRules] = React.useState<EffectiveReviewRuleDto[]>([]);
  const [activeCount, setActiveCount] = React.useState(0);
  const [isLoading, setIsLoading] = React.useState(canLoadFromApi);

  const [title, setTitle] = React.useState("");
  const [instruction, setInstruction] = React.useState("");
  const [severity, setSeverity] = React.useState<RuleSeverity>("major");
  const [category, setCategory] = React.useState<RuleCategory>("architecture");
  const [pathGlobs, setPathGlobs] = React.useState("**/*");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  const loadRules = React.useCallback(async () => {
    if (!canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<{
      items: EffectiveReviewRuleDto[];
      active_count: number;
    }>(`/api/v1/repositories/${repoId}/review-rules`, { token });
    if (res.ok) {
      setRules(res.data.items ?? []);
      setActiveCount(res.data.active_count ?? 0);
    }
  }, [canLoadFromApi, repoId, getToken]);

  React.useEffect(() => {
    if (!canLoadFromApi) return;
    let active = true;
    const run = async () => {
      try {
        const token = await resolveClientAuthToken(getToken);
        const res = await agentFetchJson<{
          items: EffectiveReviewRuleDto[];
          active_count: number;
        }>(`/api/v1/repositories/${repoId}/review-rules`, { token });
        if (active && res.ok) {
          setRules(res.data.items ?? []);
          setActiveCount(res.data.active_count ?? 0);
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, repoId, getToken, reloadNonce]);

  const handleCreateRepoRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isAdmin || !canLoadFromApi) return;
    if (!title.trim() || !instruction.trim()) {
      toast.error("Title and instruction are required.");
      return;
    }
    const globs = pathGlobs
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (globs.length === 0) {
      toast.error("At least one path glob is required.");
      return;
    }

    setIsSubmitting(true);
    try {
      const token = await resolveClientAuthToken(getToken);
      const res = await agentFetchJson<ReviewRuleDto>(
        `/api/v1/repositories/${repoId}/review-rules`,
        {
          method: "POST",
          token,
          body: {
            title: title.trim(),
            instruction: instruction.trim(),
            severity,
            category,
            path_globs: globs,
            is_enabled: true,
          },
        }
      );
      if (!res.ok) {
        toast.error(res.message);
        return;
      }
      setTitle("");
      setInstruction("");
      setPathGlobs("**/*");
      toast.success("Repository review rule created.");
      setReloadNonce((n) => n + 1);
      await loadRules();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOverrideOrgRule = async (
    rule: EffectiveReviewRuleDto,
    nextEnabled: boolean | null,
    nextSeverity: RuleSeverity | null
  ) => {
    if (!isAdmin || !canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<{
      cleared: boolean;
      effective_rule: EffectiveReviewRuleDto;
    }>(`/api/v1/repositories/${repoId}/review-rules/${rule.id}/override`, {
      method: "PUT",
      token,
      body: {
        is_enabled: nextEnabled,
        severity_override: nextSeverity,
      },
    });
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    toast.success(
      res.data.cleared ? "Rule override cleared." : "Rule override saved."
    );
    await loadRules();
  };

  const handleToggleRepoRule = async (rule: EffectiveReviewRuleDto) => {
    if (!isAdmin || !canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<ReviewRuleDto>(
      `/api/v1/repositories/${repoId}/review-rules/${rule.id}`,
      {
        method: "PATCH",
        token,
        body: { is_enabled: !rule.is_enabled },
      }
    );
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    await loadRules();
  };

  const handleDeleteRepoRule = async (ruleId: string) => {
    if (!isAdmin || !canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<void>(
      `/api/v1/repositories/${repoId}/review-rules/${ruleId}`,
      { method: "DELETE", token }
    );
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    toast.success("Repository rule deleted.");
    await loadRules();
  };

  return (
    <div className="space-y-4 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">
          Inherited organization defaults and repository rules.
        </span>
        <Badge variant="outline" className="font-mono text-[11px]">
          {activeCount} / 25 active rules
        </Badge>
      </div>

      {isLoading ? (
        <div className="py-6 flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Loading review rules...</span>
        </div>
      ) : rules.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-muted-foreground">
          No rules configured for this repository yet.
        </div>
      ) : (
        <div className="space-y-2.5 max-h-64 overflow-y-auto pr-1">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className="rounded-lg border border-border bg-secondary/25 p-3 space-y-2"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium text-foreground">
                    {rule.title}
                  </span>
                  <Badge variant="outline" className="text-[10px]">
                    {rule.scope === "org" ? "Org default" : "Repo rule"}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] uppercase",
                      severityToneClass(rule.severity)
                    )}
                  >
                    {rule.severity}
                  </Badge>
                  {rule.has_override && (
                    <Badge variant="waiting" className="text-[10px]">
                      Overridden
                    </Badge>
                  )}
                  {!rule.is_enabled && (
                    <Badge variant="cancelled" className="text-[10px]">
                      Disabled
                    </Badge>
                  )}
                </div>

                {isAdmin && rule.scope === "repo" && (
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-6 text-[11px] px-2"
                      onClick={() => void handleToggleRepoRule(rule)}
                    >
                      {rule.is_enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete repo rule ${rule.title}`}
                      className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                      onClick={() => void handleDeleteRepoRule(rule.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                )}

                {isAdmin && rule.scope === "org" && (
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-6 text-[11px] px-2"
                      onClick={() =>
                        void handleOverrideOrgRule(
                          rule,
                          !rule.is_enabled,
                          rule.override_severity
                        )
                      }
                    >
                      {rule.is_enabled ? "Disable for repo" : "Enable for repo"}
                    </Button>
                    {rule.has_override && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 text-[11px] px-2 gap-1"
                        onClick={() =>
                          void handleOverrideOrgRule(rule, null, null)
                        }
                      >
                        <RotateCcw className="h-3 w-3" />
                        <span>Reset</span>
                      </Button>
                    )}
                  </div>
                )}
              </div>

              <p className="text-muted-foreground">{rule.instruction}</p>
            </div>
          ))}
        </div>
      )}

      {isAdmin && (
        <form
          onSubmit={handleCreateRepoRule}
          className="rounded-lg border border-border bg-card p-3 space-y-2.5"
        >
          <div className="font-medium text-foreground">Add Repository Rule</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <Input
              aria-label="Repository rule title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Rule title"
              className="text-xs"
            />
            <Select
              value={severity}
              onValueChange={(v) => setSeverity(v as RuleSeverity)}
            >
              <SelectTrigger
                aria-label="Repository rule severity"
                className="text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="critical">Critical</SelectItem>
                <SelectItem value="major">Major</SelectItem>
                <SelectItem value="minor">Minor</SelectItem>
                <SelectItem value="info">Info</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={category}
              onValueChange={(v) => setCategory(v as RuleCategory)}
            >
              <SelectTrigger
                aria-label="Repository rule category"
                className="text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="security">Security</SelectItem>
                <SelectItem value="bug">Bug</SelectItem>
                <SelectItem value="performance">Performance</SelectItem>
                <SelectItem value="architecture">Architecture</SelectItem>
                <SelectItem value="style">Style</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <Input
              aria-label="Repository rule instruction"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Instruction for reviewer"
              className="text-xs sm:col-span-2"
            />
            <Input
              aria-label="Repository rule path globs"
              value={pathGlobs}
              onChange={(e) => setPathGlobs(e.target.value)}
              placeholder="**/*"
              className="font-mono text-xs"
            />
          </div>
          <div className="flex justify-end">
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting}
              className="gap-1.5"
            >
              {isSubmitting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              <span>Add Repo Rule</span>
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export function RepoExamplePRsTab({
  repoId,
  canLoadFromApi,
  isAdmin,
  getToken,
}: RepoTabBaseProps) {
  const [examples, setExamples] = React.useState<ReviewExampleDto[]>([]);
  const [isLoading, setIsLoading] = React.useState(canLoadFromApi);
  const [prRef, setPrRef] = React.useState("");
  const [classification, setClassification] = React.useState<"good" | "bad">(
    "good"
  );
  const [guidanceNote, setGuidanceNote] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);

  const loadExamples = React.useCallback(async () => {
    if (!canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<{ items: ReviewExampleDto[] }>(
      `/api/v1/repositories/${repoId}/review-examples`,
      { token }
    );
    if (res.ok) {
      setExamples(res.data.items ?? []);
    }
  }, [canLoadFromApi, repoId, getToken]);

  React.useEffect(() => {
    if (!canLoadFromApi) return;
    let active = true;
    const run = async () => {
      try {
        const token = await resolveClientAuthToken(getToken);
        const res = await agentFetchJson<{ items: ReviewExampleDto[] }>(
          `/api/v1/repositories/${repoId}/review-examples`,
          { token }
        );
        if (active && res.ok) {
          setExamples(res.data.items ?? []);
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, repoId, getToken]);

  const handleAttachExample = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isAdmin || !canLoadFromApi) return;
    const raw = prRef.trim();
    if (!raw || !guidanceNote.trim()) {
      toast.error("PR number or URL and guidance note are required.");
      return;
    }
    const isNumeric = /^\d+$/.test(raw);
    setIsSubmitting(true);
    try {
      const token = await resolveClientAuthToken(getToken);
      const res = await agentFetchJson<ReviewExampleDto>(
        `/api/v1/repositories/${repoId}/review-examples`,
        {
          method: "POST",
          token,
          body: {
            pr_number: isNumeric ? Number(raw) : null,
            pr_url: isNumeric ? null : raw,
            classification,
            guidance_note: guidanceNote.trim(),
          },
        }
      );
      if (!res.ok) {
        toast.error(res.message);
        return;
      }
      setPrRef("");
      setGuidanceNote("");
      toast.success("Example PR attached and cached.");
      await loadExamples();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRefresh = async (exampleId: string) => {
    if (!isAdmin || !canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<ReviewExampleDto>(
      `/api/v1/repositories/${repoId}/review-examples/${exampleId}/refresh`,
      { method: "POST", token }
    );
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    toast.success("Example PR diff summary refreshed.");
    await loadExamples();
  };

  const handleDelete = async (exampleId: string) => {
    if (!isAdmin || !canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<void>(
      `/api/v1/repositories/${repoId}/review-examples/${exampleId}`,
      { method: "DELETE", token }
    );
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    toast.success("Example PR removed.");
    await loadExamples();
  };

  return (
    <div className="space-y-4 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">
          Curated good and anti-pattern pull requests used as in-context
          examples.
        </span>
        <Badge variant="outline" className="font-mono text-[11px]">
          {examples.length} / 5 examples
        </Badge>
      </div>

      {isLoading ? (
        <div className="py-6 flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Loading example pull requests...</span>
        </div>
      ) : examples.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-muted-foreground">
          No curated example pull requests attached yet.
        </div>
      ) : (
        <div className="space-y-2.5 max-h-64 overflow-y-auto pr-1">
          {examples.map((ex) => (
            <div
              key={ex.id}
              className="rounded-lg border border-border bg-secondary/25 p-3 space-y-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Badge
                    variant={
                      ex.classification === "good" ? "succeeded" : "failed"
                    }
                    className="text-[10px] uppercase"
                  >
                    {ex.classification}
                  </Badge>
                  <a
                    href={ex.pr_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-foreground hover:underline truncate flex items-center gap-1"
                  >
                    <span>
                      PR #{ex.pr_number}: {ex.pr_title}
                    </span>
                    <ExternalLink className="h-3 w-3 shrink-0" />
                  </a>
                </div>

                {isAdmin && (
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Refresh example PR #${ex.pr_number}`}
                      className="h-6 w-6 p-0"
                      onClick={() => void handleRefresh(ex.id)}
                    >
                      <RefreshCw className="h-3 w-3" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete example PR #${ex.pr_number}`}
                      className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                      onClick={() => void handleDelete(ex.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                )}
              </div>

              <p className="text-muted-foreground">{ex.guidance_note}</p>
              <div className="text-[10px] font-mono text-muted-foreground">
                {ex.modified_files.length} files · {ex.cached_token_count}{" "}
                tokens cached
              </div>
            </div>
          ))}
        </div>
      )}

      {isAdmin && (
        <form
          onSubmit={handleAttachExample}
          className="rounded-lg border border-border bg-card p-3 space-y-2.5"
        >
          <div className="font-medium text-foreground">Attach Example PR</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <Input
              aria-label="Example PR number or URL"
              value={prRef}
              onChange={(e) => setPrRef(e.target.value)}
              placeholder="PR # or GitHub PR URL"
              className="text-xs sm:col-span-2 font-mono"
            />
            <Select
              value={classification}
              onValueChange={(v) => setClassification(v as "good" | "bad")}
            >
              <SelectTrigger
                aria-label="Example classification"
                className="text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="good">Good Pattern</SelectItem>
                <SelectItem value="bad">Anti-Pattern (Bad)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Input
            aria-label="Example guidance note"
            value={guidanceNote}
            onChange={(e) => setGuidanceNote(e.target.value)}
            placeholder="Explain why this PR is a good or bad example..."
            className="text-xs"
          />
          <div className="flex justify-end">
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting}
              className="gap-1.5"
            >
              {isSubmitting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              <span>Attach PR</span>
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export function RepoLearnedPreferencesTab({
  repoId,
  canLoadFromApi,
  isAdmin,
  getToken,
}: RepoTabBaseProps) {
  const [prefs, setPrefs] = React.useState<LearnedPreferenceDto[]>([]);
  const [isLoading, setIsLoading] = React.useState(canLoadFromApi);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editInstruction, setEditInstruction] = React.useState("");
  const [editStatus, setEditStatus] = React.useState<
    "active" | "dampened" | "suppressed"
  >("active");

  const loadPreferences = React.useCallback(async () => {
    if (!canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<{ items: LearnedPreferenceDto[] }>(
      `/api/v1/repositories/${repoId}/review-preferences?limit=100`,
      { token }
    );
    if (res.ok) {
      setPrefs(res.data.items ?? []);
    }
  }, [canLoadFromApi, repoId, getToken]);

  React.useEffect(() => {
    if (!canLoadFromApi) return;
    let active = true;
    const run = async () => {
      try {
        const token = await resolveClientAuthToken(getToken);
        const res = await agentFetchJson<{ items: LearnedPreferenceDto[] }>(
          `/api/v1/repositories/${repoId}/review-preferences?limit=100`,
          { token }
        );
        if (active && res.ok) {
          setPrefs(res.data.items ?? []);
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, repoId, getToken]);

  const handleSavePref = async (prefId: string) => {
    if (!isAdmin || !canLoadFromApi) return;
    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<LearnedPreferenceDto>(
      `/api/v1/repositories/${repoId}/review-preferences/${prefId}`,
      {
        method: "PATCH",
        token,
        body: {
          status: editStatus,
          instruction: editInstruction.trim() || null,
        },
      }
    );
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    setEditingId(null);
    toast.success("Learned preference updated.");
    await loadPreferences();
  };

  return (
    <div className="space-y-4 text-xs">
      <p className="text-muted-foreground">
        Preferences learned automatically when developers accept or dismiss
        findings in GitHub or the Reviews console.
      </p>

      {isLoading ? (
        <div className="py-6 flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Loading learned preferences...</span>
        </div>
      ) : prefs.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-muted-foreground">
          No learned preferences recorded for this repository yet.
        </div>
      ) : (
        <div className="space-y-2.5 max-h-72 overflow-y-auto pr-1">
          {prefs.map((pref) => {
            const isEditing = editingId === pref.id;
            return (
              <div
                key={pref.id}
                className="rounded-lg border border-border bg-secondary/25 p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <code className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[11px] text-foreground">
                      {pref.pattern_key}
                    </code>
                    <Badge
                      variant={
                        pref.status === "active"
                          ? "succeeded"
                          : pref.status === "dampened"
                            ? "waiting"
                            : "cancelled"
                      }
                      className="text-[10px]"
                    >
                      {pref.status}
                    </Badge>
                  </div>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {pref.accept_count} acc · {pref.dismiss_count} dis (streak{" "}
                    {pref.consecutive_dismissals})
                  </span>
                </div>

                {!isEditing ? (
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-muted-foreground">{pref.instruction}</p>
                    {isAdmin && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-6 text-[11px] px-2 shrink-0"
                        onClick={() => {
                          setEditingId(pref.id);
                          setEditInstruction(pref.instruction);
                          setEditStatus(pref.status);
                        }}
                      >
                        Edit
                      </Button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2 pt-1">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <Input
                        aria-label="Preference instruction"
                        value={editInstruction}
                        onChange={(e) => setEditInstruction(e.target.value)}
                        className="text-xs sm:col-span-2"
                      />
                      <Select
                        value={editStatus}
                        onValueChange={(v) =>
                          setEditStatus(
                            v as "active" | "dampened" | "suppressed"
                          )
                        }
                      >
                        <SelectTrigger
                          aria-label="Preference status"
                          className="text-xs"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="active">Active</SelectItem>
                          <SelectItem value="dampened">Dampened</SelectItem>
                          <SelectItem value="suppressed">Suppressed</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 text-[11px]"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="h-6 text-[11px]"
                        onClick={() => void handleSavePref(pref.id)}
                      >
                        Save
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
