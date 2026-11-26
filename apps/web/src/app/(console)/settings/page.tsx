import * as React from "react";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { ClerkSettingsView } from "./clerk-settings-view";
import { SettingsUnauthorizedView, SettingsView } from "./settings-view";

async function SettingsContent() {
  const session = await requireConsoleOrg();

  if (!session.isAdmin) {
    return <SettingsUnauthorizedView />;
  }

  if (isClerkPublishableKeyConfigured() && !session.isPlaceholderBypass) {
    return <ClerkSettingsView />;
  }

  return <SettingsView />;
}

export default function SettingsPage() {
  return (
    <React.Suspense
      fallback={
        <div className="h-64 max-w-4xl rounded-xl border border-border bg-card animate-pulse" />
      }
    >
      <SettingsContent />
    </React.Suspense>
  );
}
