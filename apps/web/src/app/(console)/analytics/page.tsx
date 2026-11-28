import * as React from "react";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { ClerkAnalyticsView } from "./clerk-analytics-view";
import { AnalyticsView } from "./analytics-view";

async function AnalyticsContent() {
  const session = await requireConsoleOrg();
  if (isClerkPublishableKeyConfigured() && !session.isPlaceholderBypass) {
    return <ClerkAnalyticsView />;
  }
  return <AnalyticsView />;
}

export default function AnalyticsPage() {
  return (
    <React.Suspense
      fallback={
        <div className="h-64 rounded-xl border border-border bg-card animate-pulse" />
      }
    >
      <AnalyticsContent />
    </React.Suspense>
  );
}
