"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { SettingsView } from "./settings-view";

export function ClerkSettingsView() {
  const { getToken } = useAuth();
  const memoizedGetToken = React.useCallback(async () => {
    return await getToken();
  }, [getToken]);

  return <SettingsView canPersistToApi getToken={memoizedGetToken} />;
}
