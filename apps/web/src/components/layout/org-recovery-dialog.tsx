"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { OrganizationList, useSession } from "@clerk/nextjs";
import { AlertTriangle, RefreshCw } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { isClerkPublishableKeyConfigured } from "@/lib/clerk-config";
import {
  ORG_FORBIDDEN_EVENT,
  type OrgForbiddenDetail,
} from "@/lib/org-recovery";

function ClerkRecoveryControls({
  onReloadComplete,
}: {
  onReloadComplete: () => void;
}) {
  const { session } = useSession();
  const router = useRouter();
  const [reloading, setReloading] = React.useState(false);

  const handleReload = async () => {
    setReloading(true);
    try {
      await session?.reload();
      onReloadComplete();
      router.push("/tasks");
      router.refresh();
    } finally {
      setReloading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-background/60 p-2 overflow-hidden">
        <OrganizationList
          hidePersonal
          afterSelectOrganizationUrl="/tasks"
          afterCreateOrganizationUrl="/tasks"
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleReload}
          disabled={reloading}
          className="gap-1.5"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${reloading ? "animate-spin" : ""}`}
          />
          <span>{reloading ? "Reloading session..." : "Reload session"}</span>
        </Button>
      </div>
    </div>
  );
}

export interface OrgRecoveryDialogProps {
  initialError?: OrgForbiddenDetail | null;
}

export function OrgRecoveryDialog({
  initialError = null,
}: OrgRecoveryDialogProps) {
  const [orgError, setOrgError] = React.useState<OrgForbiddenDetail | null>(
    initialError
  );

  React.useEffect(() => {
    const handleForbidden = (event: Event) => {
      const customEvent = event as CustomEvent<OrgForbiddenDetail>;
      if (customEvent.detail) {
        setOrgError(customEvent.detail);
      }
    };

    window.addEventListener(ORG_FORBIDDEN_EVENT, handleForbidden);
    return () => {
      window.removeEventListener(ORG_FORBIDDEN_EVENT, handleForbidden);
    };
  }, []);

  const clerkConfigured = isClerkPublishableKeyConfigured();

  return (
    <Dialog
      open={Boolean(orgError)}
      onOpenChange={(open) => {
        if (!open) {
          setOrgError(null);
        }
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-amber-400">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>
              {orgError?.code === "org_inactive"
                ? "Organization Inactive or Removed"
                : "Active Organization Required"}
            </span>
          </DialogTitle>
          <DialogDescription>
            {orgError?.message ||
              "Select or create an active organization to continue working in the console."}
          </DialogDescription>
        </DialogHeader>

        {clerkConfigured ? (
          <ClerkRecoveryControls onReloadComplete={() => setOrgError(null)} />
        ) : (
          <div className="rounded-lg border border-border bg-muted/40 p-4 text-xs text-muted-foreground">
            Switch to an active organization or configure live Clerk keys to
            reload your session.
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
