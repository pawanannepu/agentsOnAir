"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { ReviewsView } from "./reviews-view";

export function ClerkReviewsView() {
  const { getToken } = useAuth();
  const memoizedGetToken = React.useCallback(async () => {
    return await getToken();
  }, [getToken]);

  return <ReviewsView canLoadFromApi getToken={memoizedGetToken} />;
}
