import * as React from "react";
import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { OrganizationList, TaskChooseOrganization } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import {
  assertClerkConfiguredForRequest,
  shouldBypassClerkInNonProd,
} from "@/lib/clerk-config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

async function OrganizationOnboardingContent() {
  assertClerkConfiguredForRequest();

  if (shouldBypassClerkInNonProd()) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-base">
            Organization Onboarding (Placeholder Mode)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-xs text-muted-foreground">
          <p>
            Clerk keys are currently using placeholder values. Configure real
            Clerk keys to select or create an organization.
          </p>
          <Button asChild size="sm" className="w-full">
            <Link href="/tasks">Continue to Tasks</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  const { userId, orgId, sessionStatus } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  if (orgId && sessionStatus !== "pending") {
    redirect("/tasks");
  }

  if (sessionStatus === "pending") {
    return <TaskChooseOrganization redirectUrlComplete="/tasks" />;
  }

  return (
    <OrganizationList
      hidePersonal
      afterCreateOrganizationUrl="/tasks"
      afterSelectOrganizationUrl="/tasks"
    />
  );
}

export default function OrganizationOnboardingPage() {
  return (
    <div className="w-full space-y-6">
      <div className="text-center space-y-1.5">
        <h1 className="text-xl font-bold tracking-tight text-foreground">
          Select or create an organization
        </h1>
        <p className="text-xs text-muted-foreground">
          Every repository, sandbox run, and audit log is isolated per Clerk
          organization.
        </p>
      </div>

      <React.Suspense
        fallback={
          <div className="h-72 w-full rounded-xl border border-border bg-card animate-pulse" />
        }
      >
        <OrganizationOnboardingContent />
      </React.Suspense>
    </div>
  );
}
