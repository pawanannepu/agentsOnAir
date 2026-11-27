import * as React from "react";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { ClerkTaskDetail } from "./clerk-task-detail";
import { TaskDetailClient } from "./task-detail-client";

async function TaskDetailContent({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await requireConsoleOrg();
  const resolvedParams = await params;
  const taskId = resolvedParams.id || "018f6c38-8921-7000-8000-000000000001";

  if (isClerkPublishableKeyConfigured() && !session.isPlaceholderBypass) {
    return (
      <ClerkTaskDetail
        taskId={taskId}
        initialOrgId={session.orgId}
        isAdmin={session.isAdmin}
      />
    );
  }

  return (
    <TaskDetailClient
      taskId={taskId}
      orgId={session.orgId}
      isAdmin={session.isAdmin}
    />
  );
}

export default function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <React.Suspense
      fallback={
        <div className="p-8 text-muted-foreground text-sm font-mono animate-pulse">
          Loading sandbox task details...
        </div>
      }
    >
      <TaskDetailContent params={params} />
    </React.Suspense>
  );
}
