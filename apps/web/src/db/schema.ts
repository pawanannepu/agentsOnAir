import { sql } from "drizzle-orm";
import {
  bigint,
  boolean,
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
    baseBranch: varchar("base_branch", { length: 100 }).notNull().default("main"),
    prNumber: integer("pr_number"),
    prUrl: varchar("pr_url", { length: 512 }),
    headCommitSha: varchar("head_commit_sha", { length: 40 }),
    prReviewStatus: varchar("pr_review_status", { length: 50 }),
    createdByClerkUserId: varchar("created_by_clerk_user_id", { length: 255 }),
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
      .where(sql`${table.status} IN ('queued', 'in_progress') AND ${table.deletedAt} IS NULL`),
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
    index("ix_review_iterations_org_created").on(
      table.orgId,
      table.createdAt
    ),
  ]
);
