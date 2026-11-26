import * as React from "react";
import Link from "next/link";
import { SignUp } from "@clerk/nextjs";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function SignUpWidget() {
  if (!isClerkPublishableKeyConfigured()) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-base">
            Clerk Sign Up (Placeholder Mode)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-xs text-muted-foreground">
          <p>
            Configure{" "}
            <code className="font-mono text-foreground">
              NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
            </code>{" "}
            and{" "}
            <code className="font-mono text-foreground">CLERK_SECRET_KEY</code>{" "}
            to enable Clerk registration in development.
          </p>
          <Button asChild size="sm" className="w-full">
            <Link href="/tasks">Continue to Console</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <SignUp
      path="/sign-up"
      routing="path"
      signInUrl="/sign-in"
      fallbackRedirectUrl="/tasks"
    />
  );
}

export default function SignUpPage() {
  return (
    <div className="w-full space-y-6">
      <div className="text-center space-y-1.5">
        <h1 className="text-xl font-bold tracking-tight text-foreground">
          Create your agentsOnAir account
        </h1>
        <p className="text-xs text-muted-foreground">
          Set up your developer profile and join or create a team organization.
        </p>
      </div>

      <React.Suspense
        fallback={
          <div className="h-96 w-full rounded-xl border border-border bg-card animate-pulse" />
        }
      >
        <SignUpWidget />
      </React.Suspense>
    </div>
  );
}
