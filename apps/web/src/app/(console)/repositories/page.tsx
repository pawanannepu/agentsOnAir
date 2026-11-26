import * as React from "react";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { RepositoriesView } from "./repositories-view";

async function RepositoriesContent() {
  await requireConsoleOrg();
  return <RepositoriesView />;
}

export default function RepositoriesPage() {
  return (
    <React.Suspense
      fallback={
        <div className="h-64 rounded-xl border border-border bg-card animate-pulse" />
      }
    >
      <RepositoriesContent />
    </React.Suspense>
  );
}
