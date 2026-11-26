import * as React from "react";
import Link from "next/link";
import { SignIn } from "@clerk/nextjs";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function SignInWidget() {
  if (!isClerkPublishableKeyConfigured()) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-base">
            Clerk Sign In (Placeholder Mode)
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
            to enable Clerk authentication in development.
          </p>
          <Button asChild size="sm" className="w-full">
            <Link href="/tasks">Continue to Console</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <SignIn
      path="/sign-in"
      routing="path"
      signUpUrl="/sign-up"
      fallbackRedirectUrl="/tasks"
    />
  );
}

export default function SignInPage() {
  return (
    <div className="w-full space-y-6">
      <div className="text-center space-y-1.5">
        <h1 className="text-xl font-bold tracking-tight text-foreground">
          Sign in to agentsOnAir
        </h1>
        <p className="text-xs text-muted-foreground">
          Access your organization&apos;s autonomous engineering runs and code
          reviews.
        </p>
      </div>

      <React.Suspense
        fallback={
          <div className="h-96 w-full rounded-xl border border-border bg-card animate-pulse" />
        }
      >
        <SignInWidget />
      </React.Suspense>
    </div>
  );
}
