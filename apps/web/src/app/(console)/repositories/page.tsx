import * as React from "react";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { ClerkRepositoriesView } from "./clerk-repositories-view";
import { RepositoriesView } from "./repositories-view";

async function RepositoriesContent() {
  const session = await requireConsoleOrg();
  if (isClerkPublishableKeyConfigured() && !session.isPlaceholderBypass) {
    return <ClerkRepositoriesView isAdmin={session.isAdmin} />;
  }
  return <RepositoriesView isAdmin={session.isAdmin} />;
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
