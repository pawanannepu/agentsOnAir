import * as React from "react";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { HomeView } from "./home-view";

async function HomeContent() {
  await requireConsoleOrg();
  return <HomeView />;
}

export default function HomePage() {
  return (
    <React.Suspense
      fallback={
        <div className="h-64 rounded-xl border border-border bg-card animate-pulse" />
      }
    >
      <HomeContent />
    </React.Suspense>
  );
}
