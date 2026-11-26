"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { TaskDetailClient } from "./task-detail-client";

export interface ClerkTaskDetailProps {
  taskId: string;
  initialOrgId?: string;
}

export function ClerkTaskDetail({
  taskId,
  initialOrgId,
}: ClerkTaskDetailProps) {
  const { getToken, orgId } = useAuth();
  const resolvedOrgId = initialOrgId || orgId || undefined;

  const memoizedGetToken = React.useCallback(async () => {
    return await getToken();
  }, [getToken]);

  return (
    <TaskDetailClient
      taskId={taskId}
      orgId={resolvedOrgId}
      getToken={memoizedGetToken}
    />
  );
}
