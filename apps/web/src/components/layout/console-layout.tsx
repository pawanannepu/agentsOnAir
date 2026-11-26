"use client";

import * as React from "react";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { BreadcrumbProvider } from "./breadcrumb-context";
import { OrgRecoveryDialog } from "./org-recovery-dialog";
import { CommandDialog } from "@/components/ui/command-dialog";

export interface ConsoleLayoutProps {
  children: React.ReactNode;
  activeRunCount?: number;
  initialCollapsed?: boolean;
}

export function ConsoleLayout({
  children,
  activeRunCount = 0,
  initialCollapsed = false,
}: ConsoleLayoutProps) {
  const [commandOpen, setCommandOpen] = React.useState(false);

  return (
    <BreadcrumbProvider>
      <div className="flex min-h-screen bg-background text-foreground antialiased font-sans">
        {/* Sidebar in Suspense boundary for usePathname() */}
        <React.Suspense
          fallback={
            <aside className="w-60 border-r border-border bg-card/60" />
          }
        >
          <Sidebar
            activeRunCount={activeRunCount}
            initialCollapsed={initialCollapsed}
          />
        </React.Suspense>

        {/* Main Content Area */}
        <div className="flex-1 flex flex-col min-w-0">
          <React.Suspense
            fallback={
              <header className="h-14 border-b border-border bg-card/60" />
            }
          >
            <Header onOpenCommand={() => setCommandOpen(true)} />
          </React.Suspense>

          <main className="flex-1 overflow-auto p-6 md:p-8">
            <div className="max-w-7xl mx-auto w-full">{children}</div>
          </main>
        </div>

        {/* Global Command Dialog */}
        <CommandDialog open={commandOpen} onOpenChange={setCommandOpen} />

        {/* Global 403 Organization Recovery Prompt */}
        <OrgRecoveryDialog />
      </div>
    </BreadcrumbProvider>
  );
}
