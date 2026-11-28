"use client";

import * as React from "react";
import {
  BookOpenCheck,
  Plus,
  Trash2,
  Loader2,
  AlertCircle,
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
  type ReviewRuleDto,
  type RuleCategory,
  type RuleSeverity,
} from "@/lib/review-api";
import { cn } from "@/lib/utils";

export interface OrgReviewGuidelinesCardProps {
  canPersistToApi?: boolean;
  getToken?: () => Promise<string | null>;
}

export function OrgReviewGuidelinesCard({
  canPersistToApi = false,
  getToken,
}: OrgReviewGuidelinesCardProps) {
  const [rules, setRules] = React.useState<ReviewRuleDto[]>([]);
  const [isLoading, setIsLoading] = React.useState(canPersistToApi);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const [title, setTitle] = React.useState("");
  const [instruction, setInstruction] = React.useState("");
  const [severity, setSeverity] = React.useState<RuleSeverity>("major");
  const [category, setCategory] = React.useState<RuleCategory>("architecture");
  const [pathGlobs, setPathGlobs] = React.useState("**/*");
  const [isCreating, setIsCreating] = React.useState(false);

  React.useEffect(() => {
    if (!canPersistToApi) return;
    let active = true;
    const run = async () => {
      try {
        const token = await resolveClientAuthToken(getToken);
        const res = await agentFetchJson<{ items: ReviewRuleDto[] }>(
          "/api/v1/organizations/review-rules?limit=100",
          { token }
        );
        if (!active) return;
        if (res.ok) {
          setRules(res.data.items ?? []);
          setLoadError(null);
        } else {
          setLoadError(res.message);
        }
      } catch {
        if (active)
          setLoadError("Unable to load organization review guidelines.");
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [canPersistToApi, getToken]);

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !instruction.trim()) {
      toast.error("Rule title and instruction are required.");
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

    if (!canPersistToApi) {
      setRules((prev) => [
        ...prev,
        {
          id: `local-${Date.now()}`,
          org_id: "org-local",
          repo_id: null,
          title: title.trim(),
          instruction: instruction.trim(),
          severity,
          category,
          path_globs: globs,
          is_enabled: true,
          created_by: "local-admin",
        },
      ]);
      setTitle("");
      setInstruction("");
      setPathGlobs("**/*");
      toast.success("Organization review rule created.");
      return;
    }

    setIsCreating(true);
    try {
      const token = await resolveClientAuthToken(getToken);
      const res = await agentFetchJson<ReviewRuleDto>(
        "/api/v1/organizations/review-rules",
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
      setRules((prev) => [...prev, res.data]);
      setTitle("");
      setInstruction("");
      setPathGlobs("**/*");
      toast.success("Organization review rule created.");
    } catch {
      toast.error("Unable to create organization review rule.");
    } finally {
      setIsCreating(false);
    }
  };

  const handleToggleRule = async (rule: ReviewRuleDto) => {
    if (!canPersistToApi) {
      setRules((prev) =>
        prev.map((r) =>
          r.id === rule.id ? { ...r, is_enabled: !r.is_enabled } : r
        )
      );
      return;
    }

    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<ReviewRuleDto>(
      `/api/v1/organizations/review-rules/${rule.id}`,
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
    setRules((prev) => prev.map((r) => (r.id === rule.id ? res.data : r)));
    toast.success(res.data.is_enabled ? "Rule enabled." : "Rule disabled.");
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!canPersistToApi) {
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
      return;
    }

    const token = await resolveClientAuthToken(getToken);
    const res = await agentFetchJson<void>(
      `/api/v1/organizations/review-rules/${ruleId}`,
      { method: "DELETE", token }
    );
    if (!res.ok) {
      toast.error(res.message);
      return;
    }
    setRules((prev) => prev.filter((r) => r.id !== ruleId));
    toast.success("Organization review rule deleted.");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <BookOpenCheck className="h-4 w-4 text-emerald-400" />
          Organization Review Guidelines
        </CardTitle>
        <CardDescription className="text-xs">
          Default code review rules inherited by every repository in your
          organization (up to 25 active rules per repository including
          overrides).
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5 text-xs">
        {isLoading && (
          <div className="py-4 flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Loading organization review guidelines...</span>
          </div>
        )}

        {!isLoading && loadError && (
          <div className="flex items-center gap-2 text-destructive rounded-md border border-destructive/40 bg-destructive/5 p-3">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{loadError}</span>
          </div>
        )}

        {!isLoading && !loadError && rules.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-4 text-center text-muted-foreground">
            No organization default review rules configured yet. Add one below
            to guide every PR review and autonomous engineer cycle.
          </div>
        )}

        {!isLoading && rules.length > 0 && (
          <div className="space-y-2.5">
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="rounded-lg border border-border bg-secondary/25 p-3 flex flex-col sm:flex-row sm:items-start justify-between gap-3"
              >
                <div className="space-y-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-sm text-foreground">
                      {rule.title}
                    </span>
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px] uppercase",
                        severityToneClass(rule.severity)
                      )}
                    >
                      {rule.severity}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                      {rule.category}
                    </Badge>
                    {!rule.is_enabled && (
                      <Badge variant="cancelled" className="text-[10px]">
                        Disabled
                      </Badge>
                    )}
                  </div>
                  <p className="text-muted-foreground whitespace-pre-wrap">
                    {rule.instruction}
                  </p>
                  <div className="flex flex-wrap gap-1 pt-0.5">
                    {rule.path_globs.map((g) => (
                      <code
                        key={g}
                        className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-zinc-300"
                      >
                        {g}
                      </code>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void handleToggleRule(rule)}
                    className="h-7 text-xs"
                  >
                    {rule.is_enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete rule ${rule.title}`}
                    onClick={() => void handleDeleteRule(rule.id)}
                    className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create Organization Rule Form */}
        <form
          onSubmit={handleCreateRule}
          className="rounded-lg border border-border bg-card p-3.5 space-y-3"
        >
          <div className="font-medium text-foreground">
            Add Organization Rule
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1 sm:col-span-1">
              <label
                htmlFor="org-rule-title"
                className="font-medium text-foreground"
              >
                Rule Title
              </label>
              <Input
                id="org-rule-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Enforce parameterized SQL"
                className="text-xs"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="org-rule-severity"
                className="font-medium text-foreground"
              >
                Severity
              </label>
              <Select
                value={severity}
                onValueChange={(v) => setSeverity(v as RuleSeverity)}
              >
                <SelectTrigger id="org-rule-severity" className="text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="critical">Critical</SelectItem>
                  <SelectItem value="major">Major</SelectItem>
                  <SelectItem value="minor">Minor</SelectItem>
                  <SelectItem value="info">Info</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <label
                htmlFor="org-rule-category"
                className="font-medium text-foreground"
              >
                Category
              </label>
              <Select
                value={category}
                onValueChange={(v) => setCategory(v as RuleCategory)}
              >
                <SelectTrigger id="org-rule-category" className="text-xs">
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
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1 sm:col-span-2">
              <label
                htmlFor="org-rule-instruction"
                className="font-medium text-foreground"
              >
                Instruction
              </label>
              <Input
                id="org-rule-instruction"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Reject raw string interpolation in database queries."
                className="text-xs"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="org-rule-globs"
                className="font-medium text-foreground"
              >
                Path Globs
              </label>
              <Input
                id="org-rule-globs"
                value={pathGlobs}
                onChange={(e) => setPathGlobs(e.target.value)}
                placeholder="**/*"
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              size="sm"
              disabled={isCreating}
              className="gap-1.5"
            >
              {isCreating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              <span>Add Guideline</span>
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
