"use client";

import * as React from "react";
import {
  GitPullRequest,
  Check,
  X,
  RefreshCw,
  AlertCircle,
  Loader2,
  FileCode2,
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
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";
import { toast } from "@/components/ui/sonner";
import {
  agentFetchJson,
  resolveClientAuthToken,
  severityToneClass,
  type FindingFeedbackResponseDto,
  type PRReviewDetailDto,
  type PRReviewFindingDto,
  type PRReviewSummaryDto,
} from "@/lib/review-api";
import { cn } from "@/lib/utils";

export interface ReviewsViewProps {
  canLoadFromApi?: boolean;
  getToken?: () => Promise<string | null>;
}

interface RepoOption {
  id: string;
  full_name: string;
}

export function ReviewsView({
  canLoadFromApi = false,
  getToken,
}: ReviewsViewProps) {
  useBreadcrumbs([{ label: "Reviews" }]);

  const [repos, setRepos] = React.useState<RepoOption[]>([]);
  const [repoFilter, setRepoFilter] = React.useState<string>("all");
  const [reviews, setReviews] = React.useState<PRReviewSummaryDto[]>([]);
  const [totalReviews, setTotalReviews] = React.useState(0);
  const [offset, setOffset] = React.useState(0);
  const limit = 20;

  const [isLoadingList, setIsLoadingList] = React.useState(canLoadFromApi);
  const [listError, setListError] = React.useState<string | null>(null);
  const [selectedReviewId, setSelectedReviewId] = React.useState<string | null>(
    null
  );
  const [detail, setDetail] = React.useState<PRReviewDetailDto | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = React.useState(false);

  const [dismissingFindingId, setDismissingFindingId] = React.useState<
    string | null
  >(null);
  const [dismissReason, setDismissReason] = React.useState("");
  const [rememberPreference, setRememberPreference] = React.useState(false);
  const [submittingFindingId, setSubmittingFindingId] = React.useState<
    string | null
  >(null);
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
        // Ignore repo filter failure
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
    const loadReviews = async () => {
      setIsLoadingList(true);
      setListError(null);
      try {
        const token = await resolveClientAuthToken(getToken);
        const params = new URLSearchParams({
          limit: String(limit),
          offset: String(offset),
        });
        if (repoFilter !== "all") {
          params.set("repo_id", repoFilter);
        }
        const res = await agentFetchJson<{
          items: PRReviewSummaryDto[];
          total: number;
        }>(`/api/v1/reviews?${params.toString()}`, { token });
        if (!active) return;
        if (res.ok) {
          setReviews(res.data.items ?? []);
          setTotalReviews(res.data.total ?? 0);
          if (
            res.data.items.length > 0 &&
            (!selectedReviewId ||
              !res.data.items.some((r) => r.id === selectedReviewId))
          ) {
            setSelectedReviewId(res.data.items[0].id);
          } else if (res.data.items.length === 0) {
            setSelectedReviewId(null);
            setDetail(null);
          }
        } else {
          setListError(res.message);
        }
      } catch {
        if (active) {
          setListError("Unable to reach agent engine to load reviews.");
        }
      } finally {
        if (active) setIsLoadingList(false);
      }
    };
    void loadReviews();
    return () => {
      active = false;
    };
  }, [
    canLoadFromApi,
    repoFilter,
    offset,
    reloadNonce,
    selectedReviewId,
    getToken,
  ]);

  React.useEffect(() => {
    if (!canLoadFromApi || !selectedReviewId) return;
    let active = true;
    const loadDetail = async () => {
      setIsLoadingDetail(true);
      try {
        const token = await resolveClientAuthToken(getToken);
        const res = await agentFetchJson<PRReviewDetailDto>(
          `/api/v1/reviews/${selectedReviewId}`,
          { token }
        );
        if (active && res.ok) {
          setDetail(res.data);
        }
      } finally {
        if (active) setIsLoadingDetail(false);
      }
    };
    void loadDetail();
    return () => {
      active = false;
    };
  }, [canLoadFromApi, selectedReviewId, getToken]);

  const submitFeedback = async (
    finding: PRReviewFindingDto,
    feedbackType: "accepted" | "dismissed",
    reason?: string,
    remember?: boolean
  ) => {
    if (!canLoadFromApi) return;
    setSubmittingFindingId(finding.id);
    try {
      const token = await resolveClientAuthToken(getToken);
      const res = await agentFetchJson<FindingFeedbackResponseDto>(
        `/api/v1/reviews/findings/${finding.id}/feedback`,
        {
          method: "POST",
          token,
          body: {
            feedback_type: feedbackType,
            reason: reason?.trim() ? reason.trim() : null,
            remember_preference: Boolean(remember),
          },
        }
      );
      if (!res.ok) {
        toast.error(res.message);
        return;
      }

      setDetail((prev) =>
        prev
          ? {
              ...prev,
              findings: prev.findings.map((f) =>
                f.id === finding.id
                  ? {
                      ...f,
                      feedback_state: res.data.finding.feedback_state,
                      status: res.data.finding.status,
                    }
                  : f
              ),
            }
          : prev
      );
      setDismissingFindingId(null);
      setDismissReason("");
      setRememberPreference(false);

      const prefStatus = res.data.learned_preference?.status;
      if (feedbackType === "accepted") {
        toast.success("Finding marked accepted.");
      } else if (prefStatus === "suppressed") {
        toast.success("Finding dismissed. Pattern is now suppressed.");
      } else if (prefStatus === "dampened") {
        toast.success(
          "Finding dismissed. Pattern is now dampened to advisory."
        );
      } else {
        toast.success("Finding dismissed.");
      }
    } catch {
      toast.error("Unable to submit finding feedback.");
    } finally {
      setSubmittingFindingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Pull Request Reviews
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Inspect automated code reviews and accept or dismiss findings to
            teach repository review preferences.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Select
            value={repoFilter}
            onValueChange={(val) => {
              setRepoFilter(val);
              setOffset(0);
            }}
          >
            <SelectTrigger
              aria-label="Filter reviews by repository"
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
            aria-label="Refresh reviews"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Refresh</span>
          </Button>
        </div>
      </div>

      {isLoadingList && (
        <div className="h-64 rounded-xl border border-border bg-card animate-pulse" />
      )}

      {!isLoadingList && listError && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="py-5 flex items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-2 text-destructive">
              <AlertCircle className="h-4 w-4" />
              <span>{listError}</span>
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

      {!isLoadingList && !listError && reviews.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center space-y-2">
            <GitPullRequest className="h-8 w-8 text-muted-foreground mx-auto" />
            <p className="text-sm font-medium text-foreground">
              No pull request reviews yet
            </p>
            <p className="text-xs text-muted-foreground max-w-md mx-auto">
              Open a pull request on a connected repository or comment{" "}
              <code className="font-mono">@agentsonair review</code> to start a
              full context review.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoadingList && !listError && reviews.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Review list */}
          <div className="lg:col-span-5 space-y-2.5">
            {reviews.map((rev) => {
              const selected = rev.id === selectedReviewId;
              return (
                <button
                  key={rev.id}
                  type="button"
                  onClick={() => setSelectedReviewId(rev.id)}
                  className={cn(
                    "w-full text-left rounded-xl border p-3.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "border-emerald-500/50 bg-accent/70"
                      : "border-border bg-card hover:bg-accent/40"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground truncate">
                      {rev.repo_full_name ?? "Repository"} · PR #{rev.pr_number}
                    </span>
                    <Badge
                      variant={
                        rev.verdict === "approved"
                          ? "succeeded"
                          : rev.verdict === "changes_requested"
                            ? "failed"
                            : "outline"
                      }
                      className="text-[10px]"
                    >
                      {rev.verdict ?? rev.status}
                    </Badge>
                  </div>
                  <div className="font-medium text-sm text-foreground mt-1 truncate">
                    {rev.pr_title}
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground font-mono mt-2">
                    <span>by {rev.pr_author}</span>
                    <span>
                      {rev.findings_count ?? 0} findings ·{" "}
                      {rev.execution_duration_ms !== null &&
                      rev.execution_duration_ms !== undefined
                        ? `${rev.execution_duration_ms}ms`
                        : rev.status}
                    </span>
                  </div>
                </button>
              );
            })}

            {totalReviews > limit && (
              <div className="flex items-center justify-between pt-2 text-xs">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - limit))}
                >
                  Previous
                </Button>
                <span className="font-mono text-muted-foreground">
                  {offset + 1}–{Math.min(offset + limit, totalReviews)} of{" "}
                  {totalReviews}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={offset + limit >= totalReviews}
                  onClick={() => setOffset((o) => o + limit)}
                >
                  Next
                </Button>
              </div>
            )}
          </div>

          {/* Review Findings Detail */}
          <div className="lg:col-span-7">
            <Card>
              {isLoadingDetail && (
                <CardContent className="py-12 flex items-center justify-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Loading review findings...</span>
                </CardContent>
              )}

              {!isLoadingDetail && !detail && (
                <CardContent className="py-12 text-center text-xs text-muted-foreground">
                  Select a pull request review to inspect findings.
                </CardContent>
              )}

              {!isLoadingDetail && detail && (
                <>
                  <CardHeader className="border-b border-border pb-4">
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle className="text-base">
                        PR #{detail.pr_number}: {detail.pr_title}
                      </CardTitle>
                      <Badge
                        variant="outline"
                        className="font-mono text-[11px]"
                      >
                        {detail.findings.length} findings
                      </Badge>
                    </div>
                    <CardDescription className="text-xs font-mono">
                      Author: {detail.pr_author} · Model: {detail.model_name} ·
                      Tokens: {detail.context_token_count.toLocaleString()}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="pt-4 space-y-4">
                    {detail.findings.length === 0 ? (
                      <div className="py-8 text-center text-xs text-muted-foreground">
                        Zero findings reported on this pull request review.
                      </div>
                    ) : (
                      detail.findings.map((finding) => {
                        const isDismissing = dismissingFindingId === finding.id;
                        const isSubmitting = submittingFindingId === finding.id;
                        return (
                          <div
                            key={finding.id}
                            className="rounded-lg border border-border bg-secondary/20 p-3.5 space-y-2.5"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex items-center gap-2">
                                <Badge
                                  variant="outline"
                                  className={cn(
                                    "text-[10px] uppercase",
                                    severityToneClass(finding.severity)
                                  )}
                                >
                                  {finding.severity}
                                </Badge>
                                <Badge
                                  variant="outline"
                                  className="text-[10px]"
                                >
                                  {finding.category}
                                </Badge>
                                <span className="font-mono text-xs text-muted-foreground flex items-center gap-1">
                                  <FileCode2 className="h-3.5 w-3.5" />
                                  {finding.file_path}:{finding.line_number}
                                </span>
                              </div>

                              <Badge
                                variant={
                                  finding.feedback_state === "accepted"
                                    ? "succeeded"
                                    : finding.feedback_state === "dismissed"
                                      ? "cancelled"
                                      : "outline"
                                }
                                className="text-[10px]"
                              >
                                {finding.feedback_state === "none"
                                  ? "Open"
                                  : finding.feedback_state}
                              </Badge>
                            </div>

                            <div className="text-sm font-medium text-foreground">
                              {finding.title}
                            </div>
                            <p className="text-xs text-muted-foreground whitespace-pre-wrap">
                              {finding.message}
                            </p>

                            {finding.suggested_patch && (
                              <pre className="rounded-md border border-border bg-zinc-950 p-2.5 text-[11px] font-mono text-emerald-300 overflow-x-auto">
                                {finding.suggested_patch}
                              </pre>
                            )}

                            <div className="flex flex-wrap items-center gap-2 pt-1">
                              <Button
                                type="button"
                                size="sm"
                                variant={
                                  finding.feedback_state === "accepted"
                                    ? "default"
                                    : "outline"
                                }
                                disabled={isSubmitting}
                                onClick={() =>
                                  void submitFeedback(finding, "accepted")
                                }
                                className="h-7 text-xs gap-1"
                              >
                                <Check className="h-3.5 w-3.5" />
                                <span>Accept</span>
                              </Button>

                              <Button
                                type="button"
                                size="sm"
                                variant={
                                  finding.feedback_state === "dismissed"
                                    ? "secondary"
                                    : "outline"
                                }
                                disabled={isSubmitting}
                                onClick={() => {
                                  if (isDismissing) {
                                    setDismissingFindingId(null);
                                  } else {
                                    setDismissingFindingId(finding.id);
                                    setDismissReason("");
                                    setRememberPreference(false);
                                  }
                                }}
                                className="h-7 text-xs gap-1"
                              >
                                <X className="h-3.5 w-3.5" />
                                <span>Dismiss</span>
                              </Button>
                            </div>

                            {isDismissing && (
                              <div className="rounded-md border border-border bg-card p-3 space-y-2.5 text-xs">
                                <div className="space-y-1">
                                  <label
                                    htmlFor={`dismiss-reason-${finding.id}`}
                                    className="font-medium text-foreground"
                                  >
                                    Optional reason
                                  </label>
                                  <Input
                                    id={`dismiss-reason-${finding.id}`}
                                    value={dismissReason}
                                    onChange={(e) =>
                                      setDismissReason(e.target.value)
                                    }
                                    placeholder="e.g. Intentional helper convention in this service"
                                    className="text-xs"
                                  />
                                </div>
                                <label className="flex items-center gap-2 cursor-pointer text-muted-foreground">
                                  <input
                                    type="checkbox"
                                    checked={rememberPreference}
                                    onChange={(e) =>
                                      setRememberPreference(e.target.checked)
                                    }
                                    className="h-4 w-4 rounded border-border accent-emerald-500"
                                  />
                                  <span>
                                    Remember team preference across future
                                    reviews
                                  </span>
                                </label>
                                <div className="flex justify-end gap-2">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setDismissingFindingId(null)}
                                  >
                                    Cancel
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    disabled={isSubmitting}
                                    onClick={() =>
                                      void submitFeedback(
                                        finding,
                                        "dismissed",
                                        dismissReason,
                                        rememberPreference
                                      )
                                    }
                                  >
                                    Confirm Dismiss
                                  </Button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })
                    )}
                  </CardContent>
                </>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
