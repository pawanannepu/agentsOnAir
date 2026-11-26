import * as React from "react";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { TasksView } from "./tasks-view";

async function TasksContent() {
  await requireConsoleOrg();
  return <TasksView />;
}

export default function TasksPage() {
  return (
    <React.Suspense
      fallback={
        <div className="h-64 rounded-xl border border-border bg-card animate-pulse" />
      }
    >
      <TasksContent />
    </React.Suspense>
  );
}
