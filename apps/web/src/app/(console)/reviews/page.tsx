import * as React from "react";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import { requireConsoleOrg } from "@/lib/clerk-server";
import { ClerkReviewsView } from "./clerk-reviews-view";
import { ReviewsView } from "./reviews-view";

async function ReviewsContent() {
  const session = await requireConsoleOrg();
  if (isClerkPublishableKeyConfigured() && !session.isPlaceholderBypass) {
    return <ClerkReviewsView />;
  }
  return <ReviewsView />;
}

export default function ReviewsPage() {
  return (
    <React.Suspense
      fallback={
        <div className="h-64 rounded-xl border border-border bg-card animate-pulse" />
      }
    >
      <ReviewsContent />
    </React.Suspense>
  );
}
