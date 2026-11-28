import { sql } from "drizzle-orm";
import {
  bigint,
  boolean,
  customType,
  index,
  integer,
  jsonb,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";

const bytea = customType<{ data: Buffer; notNull: true; default: false }>({
  dataType() {
    return "bytea";
  },
});

export const organizations = pgTable(
  "organizations",
  {
    id: uuid("id").primaryKey(),
    clerkOrgId: varchar("clerk_org_id", { length: 255 }).notNull().unique(),
    name: varchar("name", { length: 255 }).notNull(),
    slug: varchar("slug", { length: 255 }).notNull(),
    githubInstallationId: bigint("github_installation_id", { mode: "number" }),
    settings: jsonb("settings").notNull().default({}),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
  },
  (table) => [
    uniqueIndex("uq_organizations_slug_active")
      .on(table.slug)
      .where(sql`${table.deletedAt} IS NULL`),
  ]
);

export const repositories = pgTable(
  "repositories",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    githubRepoId: bigint("github_repo_id", { mode: "number" }).notNull(),
    githubInstallationId: bigint("github_installation_id", {
      mode: "number",
    }).notNull(),
    name: varchar("name", { length: 255 }).notNull(),
    fullName: varchar("full_name", { length: 255 }).notNull(),
    defaultBranch: varchar("default_branch", { length: 100 })
      .notNull()
      .default("main"),
    isPrivate: boolean("is_private").notNull().default(true),
    config: jsonb("config").notNull().default({}),
    reviewSettings: jsonb("review_settings")
      .notNull()
      .default({
        enabled: true,
        auto_review: true,
        allow_approval: false,
        ignore_all_bots: false,
        min_severity: "info",
        max_comments: 25,
        ignored_paths: ["*.lock", "dist/**", "node_modules/**"],
      }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
  },
  (table) => [
    uniqueIndex("uq_repositories_active")
      .on(table.orgId, table.githubRepoId)
      .where(sql`${table.deletedAt} IS NULL`),
    index("ix_repositories_org_name").on(table.orgId, table.name),
  ]
);

export const credentials = pgTable(
  "credentials",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id").references(() => repositories.id, {
      onDelete: "cascade",
    }),
    name: varchar("name", { length: 100 }).notNull(),
    credentialType: varchar("credential_type", { length: 50 }).notNull(),
    encryptedData: text("encrypted_data").notNull(),
    nonce: text("nonce").notNull(),
    keyVersion: integer("key_version").notNull().default(1),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_credentials_active").on(
      table.orgId,
      sql`COALESCE(${table.repoId}, '00000000-0000-0000-0000-000000000000'::uuid)`,
      table.name
    ),
  ]
);

export const tasks = pgTable(
  "tasks",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id")
      .notNull()
      .references(() => repositories.id, { onDelete: "cascade" }),
    title: varchar("title", { length: 255 }).notNull(),
    description: text("description").notNull(),
    status: varchar("status", { length: 50 }).notNull().default("queued"),
    triggerType: varchar("trigger_type", { length: 50 }).notNull(),
    triggerMetadata: jsonb("trigger_metadata").notNull().default({}),
    branchName: varchar("branch_name", { length: 255 }),
    baseBranch: varchar("base_branch", { length: 100 })
      .notNull()
      .default("main"),
    prNumber: integer("pr_number"),
    prUrl: varchar("pr_url", { length: 512 }),
    headCommitSha: varchar("head_commit_sha", { length: 40 }),
    prReviewStatus: varchar("pr_review_status", { length: 50 }),
    createdByClerkUserId: varchar("created_by_clerk_user_id", { length: 255 }),
    interruptionPrompt: text("interruption_prompt"),
    interruptionType: varchar("interruption_type", { length: 50 }),
    interruptionOptions: jsonb("interruption_options"),
    interruptionExpiresAt: timestamp("interruption_expires_at", {
      withTimezone: true,
    }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
  },
  (table) => [
    index("ix_tasks_org_status_created").on(
      table.orgId,
      table.status,
      table.createdAt
    ),
    index("ix_tasks_repo_created").on(table.repoId, table.createdAt),
    uniqueIndex("uq_tasks_active_repo_issue")
      .on(table.repoId, sql`(${table.triggerMetadata}->>'issue_number')`)
      .where(
        sql`${table.status} IN ('queued', 'in_progress', 'awaiting_input') AND ${table.deletedAt} IS NULL`
      ),
  ]
);

export const taskRuns = pgTable(
  "task_runs",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    taskId: uuid("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    runNumber: integer("run_number").notNull().default(1),
    status: varchar("status", { length: 50 }).notNull().default("pending"),
    version: integer("version").notNull().default(1),
    failureReason: text("failure_reason"),
    checkpointState: jsonb("checkpoint_state").notNull().default({}),
    promptTokens: integer("prompt_tokens").notNull().default(0),
    completionTokens: integer("completion_tokens").notNull().default(0),
    tokensUsed: integer("tokens_used").notNull().default(0),
    estimatedCostCents: integer("estimated_cost_cents").notNull().default(0),
    pausedSeconds: integer("paused_seconds").notNull().default(0),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_task_runs_task_run_number").on(
      table.taskId,
      table.runNumber
    ),
    index("ix_task_runs_org_status_created").on(
      table.orgId,
      table.status,
      table.createdAt
    ),
    index("ix_task_runs_org_status_completed").on(
      table.orgId,
      table.status,
      table.completedAt
    ),
    index("ix_task_runs_task_status").on(table.taskId, table.status),
  ]
);

export const sandboxRuns = pgTable(
  "sandbox_runs",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    taskRunId: uuid("task_run_id")
      .notNull()
      .unique()
      .references(() => taskRuns.id, { onDelete: "cascade" }),
    provider: varchar("provider", { length: 50 }).notNull(),
    sandboxId: varchar("sandbox_id", { length: 255 }).notNull(),
    status: varchar("status", { length: 50 }).notNull().default("allocating"),
    exitCode: integer("exit_code"),
    logsStorageKey: varchar("logs_storage_key", { length: 512 }),
    memoryLimitMb: integer("memory_limit_mb").notNull().default(2048),
    timeoutSeconds: integer("timeout_seconds").notNull().default(600),
    allocatedAt: timestamp("allocated_at", { withTimezone: true }),
    terminatedAt: timestamp("terminated_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_sandbox_runs_org_status").on(table.orgId, table.status),
    index("ix_sandbox_runs_sandbox_id").on(table.sandboxId),
    index("ix_sandbox_runs_status_created").on(table.status, table.createdAt),
  ]
);

export const auditLogs = pgTable(
  "audit_logs",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "restrict" }),
    actorType: varchar("actor_type", { length: 50 }).notNull(),
    actorId: varchar("actor_id", { length: 255 }).notNull(),
    action: varchar("action", { length: 100 }).notNull(),
    targetType: varchar("target_type", { length: 50 }).notNull(),
    targetId: uuid("target_id").notNull(),
    payloadBefore: jsonb("payload_before"),
    payloadAfter: jsonb("payload_after"),
    ipAddress: varchar("ip_address", { length: 45 }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_audit_logs_org_created").on(table.orgId, table.createdAt),
    index("ix_audit_logs_target").on(table.targetType, table.targetId),
  ]
);

export const reviewIterations = pgTable(
  "review_iterations",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "restrict" }),
    taskRunId: uuid("task_run_id")
      .notNull()
      .references(() => taskRuns.id, { onDelete: "cascade" }),
    cycleNumber: integer("cycle_number").notNull(),
    verdict: varchar("verdict", { length: 50 }).notNull(),
    summary: text("summary").notNull(),
    findings: jsonb("findings").notNull().default([]),
    blockingCount: integer("blocking_count").notNull().default(0),
    nonBlockingCount: integer("non_blocking_count").notNull().default(0),
    diffSnapshot: text("diff_snapshot"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_review_iterations_run_cycle").on(
      table.taskRunId,
      table.cycleNumber
    ),
    index("ix_review_iterations_org_created").on(table.orgId, table.createdAt),
  ]
);

export const taskInterventions = pgTable(
  "task_interventions",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    taskId: uuid("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    taskRunId: uuid("task_run_id").references(() => taskRuns.id, {
      onDelete: "set null",
    }),
    clerkUserId: varchar("clerk_user_id", { length: 255 }).notNull(),
    interventionType: varchar("intervention_type", { length: 50 }).notNull(),
    promptSnapshot: text("prompt_snapshot"),
    payload: jsonb("payload").notNull().default({}),
    appliedAt: timestamp("applied_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_task_interventions_task_created").on(
      table.taskId,
      table.createdAt
    ),
    index("ix_task_interventions_org_created").on(table.orgId, table.createdAt),
  ]
);

export const taskTranscripts = pgTable(
  "task_transcripts",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    taskId: uuid("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    taskRunId: uuid("task_run_id")
      .notNull()
      .unique()
      .references(() => taskRuns.id, { onDelete: "cascade" }),
    terminalLog: bytea("terminal_log").notNull(),
    eventsJson: jsonb("events_json").notNull().default([]),
    totalLines: integer("total_lines").notNull().default(0),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_task_transcripts_task_created").on(table.taskId, table.createdAt),
    index("ix_task_transcripts_org_created").on(table.orgId, table.createdAt),
  ]
);

export const taskApprovals = pgTable(
  "task_approvals",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    taskId: uuid("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    taskRunId: uuid("task_run_id")
      .notNull()
      .references(() => taskRuns.id, { onDelete: "cascade" }),
    status: varchar("status", { length: 32 }).notNull().default("pending"),
    riskCategory: varchar("risk_category", { length: 64 }).notNull(),
    actionType: varchar("action_type", { length: 64 }).notNull(),
    actionHash: varchar("action_hash", { length: 64 }).notNull(),
    actionSummary: text("action_summary").notNull(),
    actionPayload: jsonb("action_payload").notNull().default({}),
    consumedAt: timestamp("consumed_at", { withTimezone: true }),
    decidedByClerkUserId: varchar("decided_by_clerk_user_id", { length: 255 }),
    decisionNote: text("decision_note"),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    decidedAt: timestamp("decided_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_task_approvals_pending_task")
      .on(table.taskId)
      .where(sql`${table.status} = 'pending'`),
    index("ix_task_approvals_task_created").on(table.taskId, table.createdAt),
  ]
);

export const usageEvents = pgTable(
  "usage_events",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "cascade" }),
    taskRunId: uuid("task_run_id").references(() => taskRuns.id, {
      onDelete: "cascade",
    }),
    prReviewId: uuid("pr_review_id"),
    provider: varchar("provider", { length: 64 }).notNull(),
    model: varchar("model", { length: 128 }).notNull(),
    operationType: varchar("operation_type", { length: 32 }).notNull(),
    promptTokens: integer("prompt_tokens").notNull(),
    completionTokens: integer("completion_tokens").notNull(),
    estimatedCostCents: integer("estimated_cost_cents").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_usage_events_org_created").on(table.orgId, table.createdAt),
    index("ix_usage_events_task_run_created").on(
      table.taskRunId,
      table.createdAt
    ),
    index("ix_usage_events_pr_review_created").on(
      table.prReviewId,
      table.createdAt
    ),
  ]
);

export const orgMonthlyUsage = pgTable(
  "org_monthly_usage",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    billingMonth: varchar("billing_month", { length: 7 }).notNull(),
    totalTokens: bigint("total_tokens", { mode: "number" })
      .notNull()
      .default(0),
    totalCostCents: integer("total_cost_cents").notNull().default(0),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_org_monthly_usage_org_month").on(
      table.orgId,
      table.billingMonth
    ),
  ]
);

export const pullRequestReviews = pgTable(
  "pull_request_reviews",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id")
      .notNull()
      .references(() => repositories.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, {
      onDelete: "set null",
    }),
    prNumber: integer("pr_number").notNull(),
    prTitle: varchar("pr_title", { length: 512 }).notNull(),
    prAuthor: varchar("pr_author", { length: 100 }).notNull(),
    headCommitSha: varchar("head_commit_sha", { length: 40 }).notNull(),
    baseCommitSha: varchar("base_commit_sha", { length: 40 }).notNull(),
    status: varchar("status", { length: 50 }).notNull().default("pending"),
    verdict: varchar("verdict", { length: 50 }),
    summary: text("summary"),
    githubReviewId: bigint("github_review_id", { mode: "number" }),
    contextTokenCount: integer("context_token_count").notNull().default(0),
    modelName: varchar("model_name", { length: 100 }).notNull(),
    executionDurationMs: integer("execution_duration_ms"),
    errorMessage: text("error_message"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_pr_reviews_repo_pr_created").on(
      table.repoId,
      table.prNumber,
      table.createdAt
    ),
    index("ix_pr_reviews_org_created").on(table.orgId, table.createdAt),
    index("ix_pr_reviews_org_status_created").on(
      table.orgId,
      table.status,
      table.createdAt
    ),
    index("ix_pr_reviews_repo_status_created").on(
      table.repoId,
      table.status,
      table.createdAt
    ),
    uniqueIndex("uq_pr_reviews_active_pr")
      .on(table.repoId, table.prNumber)
      .where(
        sql`${table.status} IN ('pending', 'analyzing', 'reviewing', 'posting')`
      ),
  ]
);

export const reviewRules = pgTable(
  "review_rules",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id").references(() => repositories.id, {
      onDelete: "cascade",
    }),
    title: varchar("title", { length: 200 }).notNull(),
    instruction: text("instruction").notNull(),
    severity: varchar("severity", { length: 20 }).notNull(),
    category: varchar("category", { length: 50 }).notNull(),
    pathGlobs: jsonb("path_globs")
      .$type<string[]>()
      .notNull()
      .default(["**/*"]),
    isEnabled: boolean("is_enabled").notNull().default(true),
    createdBy: varchar("created_by", { length: 255 }).notNull(),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_review_rules_org_repo_enabled_active")
      .on(table.orgId, table.repoId, table.isEnabled)
      .where(sql`${table.deletedAt} IS NULL`),
  ]
);

export const reviewRuleOverrides = pgTable(
  "review_rule_overrides",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id")
      .notNull()
      .references(() => repositories.id, { onDelete: "cascade" }),
    ruleId: uuid("rule_id")
      .notNull()
      .references(() => reviewRules.id, { onDelete: "cascade" }),
    isEnabled: boolean("is_enabled"),
    severityOverride: varchar("severity_override", { length: 20 }),
    updatedBy: varchar("updated_by", { length: 255 }).notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_review_rule_overrides_repo_rule").on(
      table.repoId,
      table.ruleId
    ),
    index("ix_review_rule_overrides_org_id").on(table.orgId),
  ]
);

export const reviewExamples = pgTable(
  "review_examples",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id")
      .notNull()
      .references(() => repositories.id, { onDelete: "cascade" }),
    prNumber: integer("pr_number").notNull(),
    prUrl: varchar("pr_url", { length: 512 }).notNull(),
    prTitle: varchar("pr_title", { length: 512 }).notNull(),
    classification: varchar("classification", { length: 20 }).notNull(),
    guidanceNote: text("guidance_note").notNull(),
    modifiedFiles: jsonb("modified_files")
      .$type<string[]>()
      .notNull()
      .default([]),
    cachedDiffSummary: text("cached_diff_summary"),
    cachedTokenCount: integer("cached_token_count").notNull().default(0),
    cachedAt: timestamp("cached_at", { withTimezone: true }),
    createdBy: varchar("created_by", { length: 255 }).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_review_examples_repo_pr").on(table.repoId, table.prNumber),
    index("ix_review_examples_org_repo").on(table.orgId, table.repoId),
  ]
);

export const prReviewFindings = pgTable(
  "pr_review_findings",
  {
    id: uuid("id").primaryKey(),
    reviewId: uuid("review_id")
      .notNull()
      .references(() => pullRequestReviews.id, { onDelete: "cascade" }),
    filePath: varchar("file_path", { length: 1024 }).notNull(),
    startLine: integer("start_line"),
    lineNumber: integer("line_number").notNull(),
    side: varchar("side", { length: 10 }).notNull().default("RIGHT"),
    severity: varchar("severity", { length: 20 }).notNull(),
    category: varchar("category", { length: 50 }).notNull(),
    title: varchar("title", { length: 255 }).notNull(),
    message: text("message").notNull(),
    suggestedPatch: text("suggested_patch"),
    githubCommentId: bigint("github_comment_id", { mode: "number" }),
    status: varchar("status", { length: 30 }).notNull().default("open"),
    ruleId: uuid("rule_id").references(() => reviewRules.id, {
      onDelete: "set null",
    }),
    feedbackState: varchar("feedback_state", { length: 20 })
      .notNull()
      .default("none"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    index("ix_pr_findings_review_severity").on(table.reviewId, table.severity),
    index("ix_pr_findings_review_file").on(table.reviewId, table.filePath),
    index("ix_pr_findings_rule_feedback").on(table.ruleId, table.feedbackState),
    index("ix_pr_findings_review_feedback").on(
      table.reviewId,
      table.feedbackState
    ),
    index("ix_pr_findings_github_comment_id")
      .on(table.githubCommentId)
      .where(sql`${table.githubCommentId} IS NOT NULL`),
  ]
);

export const reviewFindingFeedback = pgTable(
  "review_finding_feedback",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id")
      .notNull()
      .references(() => repositories.id, { onDelete: "cascade" }),
    findingId: uuid("finding_id")
      .notNull()
      .references(() => prReviewFindings.id, { onDelete: "cascade" }),
    feedbackType: varchar("feedback_type", { length: 20 }).notNull(),
    source: varchar("source", { length: 32 }).notNull(),
    reason: text("reason"),
    rememberPreference: boolean("remember_preference").notNull().default(false),
    actorId: varchar("actor_id", { length: 255 }).notNull(),
    githubEventId: varchar("github_event_id", { length: 128 }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_review_finding_feedback_gh_event")
      .on(table.githubEventId)
      .where(sql`${table.githubEventId} IS NOT NULL`),
    index("ix_review_finding_feedback_finding_created").on(
      table.findingId,
      table.createdAt
    ),
    index("ix_review_finding_feedback_org_repo").on(table.orgId, table.repoId),
  ]
);

export const reviewLearnedPreferences = pgTable(
  "review_learned_preferences",
  {
    id: uuid("id").primaryKey(),
    orgId: uuid("org_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "cascade" }),
    repoId: uuid("repo_id")
      .notNull()
      .references(() => repositories.id, { onDelete: "cascade" }),
    ruleId: uuid("rule_id").references(() => reviewRules.id, {
      onDelete: "set null",
    }),
    sourceFeedbackId: uuid("source_feedback_id").references(
      () => reviewFindingFeedback.id,
      { onDelete: "set null" }
    ),
    patternKey: varchar("pattern_key", { length: 255 }).notNull(),
    instruction: text("instruction").notNull(),
    dismissCount: integer("dismiss_count").notNull().default(0),
    acceptCount: integer("accept_count").notNull().default(0),
    consecutiveDismissals: integer("consecutive_dismissals")
      .notNull()
      .default(0),
    status: varchar("status", { length: 20 }).notNull().default("active"),
    lastFeedbackAt: timestamp("last_feedback_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  },
  (table) => [
    uniqueIndex("uq_review_learned_prefs_repo_pattern").on(
      table.repoId,
      table.patternKey
    ),
    index("ix_review_learned_prefs_org_repo_status").on(
      table.orgId,
      table.repoId,
      table.status
    ),
  ]
);
