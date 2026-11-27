import { describe, expect, it } from "vitest";
import { getTableName } from "drizzle-orm";
import {
  auditLogs,
  credentials,
  orgMonthlyUsage,
  organizations,
  repositories,
  sandboxRuns,
  taskApprovals,
  taskRuns,
  tasks,
  usageEvents,
} from "@/db/schema";

describe("Drizzle ORM schema definitions (covers: AC-1, AC-2, AC-5, AC-6, AC-7)", () => {
  it("defines the seven core relational tables with correct SQL table names (covers: AC-1)", () => {
    expect(getTableName(organizations)).toBe("organizations");
    expect(getTableName(repositories)).toBe("repositories");
    expect(getTableName(credentials)).toBe("credentials");
    expect(getTableName(tasks)).toBe("tasks");
    expect(getTableName(taskRuns)).toBe("task_runs");
    expect(getTableName(sandboxRuns)).toBe("sandbox_runs");
    expect(getTableName(auditLogs)).toBe("audit_logs");
  });

  it("exports organizations table with tenant identifier and soft delete columns (covers: AC-1, AC-2, AC-7)", () => {
    expect(organizations.id).toBeDefined();
    expect(organizations.clerkOrgId).toBeDefined();
    expect(organizations.name).toBeDefined();
    expect(organizations.slug).toBeDefined();
    expect(organizations.githubInstallationId).toBeDefined();
    expect(organizations.settings).toBeDefined();
    expect(organizations.createdAt).toBeDefined();
    expect(organizations.updatedAt).toBeDefined();
    expect(organizations.deletedAt).toBeDefined();
  });

  it("exports repositories table with tenant scoping and soft delete columns (covers: AC-1, AC-2, AC-7)", () => {
    expect(repositories.id).toBeDefined();
    expect(repositories.orgId).toBeDefined();
    expect(repositories.githubRepoId).toBeDefined();
    expect(repositories.name).toBeDefined();
    expect(repositories.fullName).toBeDefined();
    expect(repositories.defaultBranch).toBeDefined();
    expect(repositories.isPrivate).toBeDefined();
    expect(repositories.config).toBeDefined();
    expect(repositories.deletedAt).toBeDefined();
  });

  it("exports credentials table with authenticated ciphertext and nonce storage (covers: AC-5)", () => {
    expect(credentials.id).toBeDefined();
    expect(credentials.orgId).toBeDefined();
    expect(credentials.repoId).toBeDefined();
    expect(credentials.name).toBeDefined();
    expect(credentials.credentialType).toBeDefined();
    expect(credentials.encryptedData).toBeDefined();
    expect(credentials.nonce).toBeDefined();
    expect(credentials.keyVersion).toBeDefined();
  });

  it("exports tasks table with status and trigger metadata (covers: AC-3)", () => {
    expect(tasks.id).toBeDefined();
    expect(tasks.orgId).toBeDefined();
    expect(tasks.repoId).toBeDefined();
    expect(tasks.title).toBeDefined();
    expect(tasks.description).toBeDefined();
    expect(tasks.status).toBeDefined();
    expect(tasks.triggerType).toBeDefined();
    expect(tasks.triggerMetadata).toBeDefined();
    expect(tasks.branchName).toBeDefined();
    expect(tasks.prNumber).toBeDefined();
  });

  it("exports taskRuns table with checkpoint state and optimistic version counter (covers: AC-3)", () => {
    expect(taskRuns.id).toBeDefined();
    expect(taskRuns.orgId).toBeDefined();
    expect(taskRuns.taskId).toBeDefined();
    expect(taskRuns.runNumber).toBeDefined();
    expect(taskRuns.status).toBeDefined();
    expect(taskRuns.version).toBeDefined();
    expect(taskRuns.checkpointState).toBeDefined();
    expect(taskRuns.tokensUsed).toBeDefined();
    expect(taskRuns.estimatedCostCents).toBeDefined();
  });

  it("exports sandboxRuns table with provider resource limits and log storage keys (covers: AC-4)", () => {
    expect(sandboxRuns.id).toBeDefined();
    expect(sandboxRuns.orgId).toBeDefined();
    expect(sandboxRuns.taskRunId).toBeDefined();
    expect(sandboxRuns.provider).toBeDefined();
    expect(sandboxRuns.sandboxId).toBeDefined();
    expect(sandboxRuns.status).toBeDefined();
    expect(sandboxRuns.memoryLimitMb).toBeDefined();
    expect(sandboxRuns.timeoutSeconds).toBeDefined();
    expect(sandboxRuns.logsStorageKey).toBeDefined();
  });

  it("exports auditLogs table with actor, action, and JSONB before after snapshots (covers: AC-6)", () => {
    expect(auditLogs.id).toBeDefined();
    expect(auditLogs.orgId).toBeDefined();
    expect(auditLogs.actorType).toBeDefined();
    expect(auditLogs.actorId).toBeDefined();
    expect(auditLogs.action).toBeDefined();
    expect(auditLogs.targetType).toBeDefined();
    expect(auditLogs.targetId).toBeDefined();
    expect(auditLogs.payloadBefore).toBeDefined();
    expect(auditLogs.payloadAfter).toBeDefined();
  });

  it("exports guardrail approvals, usage events, monthly usage, and taskRuns.pausedSeconds (covers: AC-1, AC-3, AC-5, AC-6)", () => {
    expect(taskRuns.pausedSeconds).toBeDefined();

    expect(getTableName(taskApprovals)).toBe("task_approvals");
    expect(taskApprovals.status).toBeDefined();
    expect(taskApprovals.riskCategory).toBeDefined();
    expect(taskApprovals.actionType).toBeDefined();
    expect(taskApprovals.actionHash).toBeDefined();
    expect(taskApprovals.actionSummary).toBeDefined();
    expect(taskApprovals.actionPayload).toBeDefined();
    expect(taskApprovals.consumedAt).toBeDefined();
    expect(taskApprovals.decidedByClerkUserId).toBeDefined();
    expect(taskApprovals.expiresAt).toBeDefined();

    expect(getTableName(usageEvents)).toBe("usage_events");
    expect(usageEvents.taskRunId).toBeDefined();
    expect(usageEvents.prReviewId).toBeDefined();
    expect(usageEvents.provider).toBeDefined();
    expect(usageEvents.model).toBeDefined();
    expect(usageEvents.operationType).toBeDefined();
    expect(usageEvents.estimatedCostCents).toBeDefined();

    expect(getTableName(orgMonthlyUsage)).toBe("org_monthly_usage");
    expect(orgMonthlyUsage.billingMonth).toBeDefined();
    expect(orgMonthlyUsage.totalTokens).toBeDefined();
    expect(orgMonthlyUsage.totalCostCents).toBeDefined();
  });
});
