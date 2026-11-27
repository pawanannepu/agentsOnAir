"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { RepositoriesView } from "./repositories-view";

export interface ClerkRepositoriesViewProps {
  isAdmin: boolean;
}

export function ClerkRepositoriesView({ isAdmin }: ClerkRepositoriesViewProps) {
  const { getToken } = useAuth();
  const memoizedGetToken = React.useCallback(async () => {
    return await getToken();
  }, [getToken]);

  return (
    <RepositoriesView
      canLoadFromApi
      isAdmin={isAdmin}
      getToken={memoizedGetToken}
    />
  );
}
