"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { AnalyticsView } from "./analytics-view";

export function ClerkAnalyticsView() {
  const { getToken } = useAuth();
  const memoizedGetToken = React.useCallback(async () => {
    return await getToken();
  }, [getToken]);

  return <AnalyticsView canLoadFromApi getToken={memoizedGetToken} />;
}
