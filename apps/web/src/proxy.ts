import { clerkMiddleware } from "@clerk/nextjs/server";
import {
  NextResponse,
  type NextFetchEvent,
  type NextRequest,
} from "next/server";
import { isClerkServerConfigured, isProductionEnv } from "@/lib/clerk-config";

function isPublicRoute(pathname: string): boolean {
  return (
    pathname === "/api/health" ||
    pathname === "/sign-in" ||
    pathname.startsWith("/sign-in/") ||
    pathname === "/sign-up" ||
    pathname.startsWith("/sign-up/")
  );
}

function isOnboardingRoute(pathname: string): boolean {
  return (
    pathname === "/onboarding/organization" ||
    pathname.startsWith("/onboarding/organization/")
  );
}

function isApiOrTrpcRoute(pathname: string): boolean {
  return pathname.startsWith("/api/") || pathname.startsWith("/trpc/");
}

const clerkHandler = clerkMiddleware(async (auth, req: NextRequest) => {
  const { pathname, search } = req.nextUrl;

  if (isPublicRoute(pathname) || isApiOrTrpcRoute(pathname)) {
    return;
  }

  const { userId, orgId, sessionStatus } = await auth();

  if (!userId) {
    const signInUrl = req.nextUrl.clone();
    signInUrl.pathname = "/sign-in";
    signInUrl.search = "";
    const target = `${pathname}${search}`;
    if (target && target !== "/") {
      signInUrl.searchParams.set("redirect_url", target);
    }
    return NextResponse.redirect(signInUrl, { status: 307 });
  }

  if (isOnboardingRoute(pathname)) {
    return;
  }

  if (!orgId || sessionStatus === "pending") {
    const onboardingUrl = req.nextUrl.clone();
    onboardingUrl.pathname = "/onboarding/organization";
    onboardingUrl.search = "";
    return NextResponse.redirect(onboardingUrl, { status: 307 });
  }
});

export default function proxy(req: NextRequest, event: NextFetchEvent) {
  const { pathname } = req.nextUrl;

  if (pathname === "/api/health") {
    return NextResponse.next();
  }

  if (isProductionEnv() && !isClerkServerConfigured()) {
    return NextResponse.json(
      {
        code: "clerk_not_configured",
        error:
          "Clerk authentication keys are missing or using placeholder values.",
      },
      { status: 500 }
    );
  }

  if (!isClerkServerConfigured()) {
    return NextResponse.next();
  }

  return clerkHandler(req, event);
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
