import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import {
  assertClerkConfiguredForRequest,
  shouldBypassClerkInNonProd,
} from "@/lib/clerk-config";

export interface ConsoleOrgSession {
  userId: string;
  orgId: string | undefined;
  orgSlug: string | undefined;
  orgRole: string | undefined;
  isAdmin: boolean;
  isPlaceholderBypass: boolean;
}

/**
 * Enforce an authenticated Clerk session and active organization inside
 * Server Components (wrapped in <Suspense> or paired with loading.tsx).
 *
 * In NODE_ENV=production, missing or placeholder Clerk keys fail closed
 * at request time with ClerkConfigurationError (HTTP 500) without breaking
 * `next build`. In non-production environments without Clerk keys, returns
 * a local placeholder bypass session so dev previews and Vitest run cleanly.
 */
export async function requireConsoleOrg(): Promise<ConsoleOrgSession> {
  assertClerkConfiguredForRequest();

  if (shouldBypassClerkInNonProd()) {
    return {
      userId: "dev_user",
      orgId: undefined,
      orgSlug: undefined,
      orgRole: "org:admin",
      isAdmin: true,
      isPlaceholderBypass: true,
    };
  }

  const session = await auth();
  if (!session.userId) {
    redirect("/sign-in");
  }

  if (!session.orgId || session.sessionStatus === "pending") {
    redirect("/onboarding/organization");
  }

  return {
    userId: session.userId,
    orgId: session.orgId,
    orgSlug: session.orgSlug ?? undefined,
    orgRole: session.orgRole ?? undefined,
    isAdmin: session.has({ role: "org:admin" }),
    isPlaceholderBypass: false,
  };
}
