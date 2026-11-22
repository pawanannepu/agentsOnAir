import * as React from "react";
import { TaskDetailClient } from "./task-detail-client";

async function TaskDetailContent({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = await params;
  const taskId = resolvedParams.id || "018f6c38-8921-7000-8000-000000000001";
  return <TaskDetailClient taskId={taskId} />;
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
