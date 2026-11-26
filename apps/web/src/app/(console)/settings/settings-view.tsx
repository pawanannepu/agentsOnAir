"use client";

import * as React from "react";
import Link from "next/link";
import {
  Cpu,
  Shield,
  Save,
  ShieldAlert,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";
import { toast } from "@/components/ui/sonner";
import {
  dispatchOrgForbiddenEvent,
  extractOrgForbiddenDetail,
} from "@/lib/org-recovery";

export interface SettingsViewProps {
  canPersistToApi?: boolean;
  getToken?: () => Promise<string | null>;
}

export function SettingsView({
  canPersistToApi = false,
  getToken,
}: SettingsViewProps) {
  const [provider, setProvider] = React.useState("e2b");
  const [timeoutMinutes, setTimeoutMinutes] = React.useState("10");
  const [isSaving, setIsSaving] = React.useState(false);

  useBreadcrumbs([{ label: "Settings" }]);

  React.useEffect(() => {
    if (!canPersistToApi) {
      return;
    }
    let active = true;
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    const loadSettings = async () => {
      try {
        const token = getToken
          ? await getToken()
          : typeof window !== "undefined" && window.Clerk?.session?.getToken
            ? await window.Clerk.session.getToken()
            : null;
        if (!token) {
          return;
        }
        const res = await fetch(`${baseUrl}/api/v1/organizations/settings`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 403) {
          const detail = extractOrgForbiddenDetail(
            await res.json().catch(() => null)
          );
          if (detail) {
            dispatchOrgForbiddenEvent(detail);
          }
          return;
        }
        if (!res.ok || !active) {
          return;
        }
        const data = (await res.json()) as {
          settings?: {
            sandbox_provider?: string;
            timeout_minutes?: number;
          };
        };
        if (!active || !data.settings) {
          return;
        }
        if (
          data.settings.sandbox_provider === "e2b" ||
          data.settings.sandbox_provider === "docker"
        ) {
          setProvider(data.settings.sandbox_provider);
        }
        if (typeof data.settings.timeout_minutes === "number") {
          setTimeoutMinutes(String(data.settings.timeout_minutes));
        }
      } catch {
        // Keep defaults if engine is offline during preview
      }
    };

    void loadSettings();
    return () => {
      active = false;
    };
  }, [canPersistToApi, getToken]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!canPersistToApi) {
      toast.success("Workspace configuration saved successfully.");
      return;
    }

    setIsSaving(true);
    const baseUrl =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000";

    try {
      const token = getToken
        ? await getToken()
        : typeof window !== "undefined" && window.Clerk?.session?.getToken
          ? await window.Clerk.session.getToken()
          : null;

      const res = await fetch(`${baseUrl}/api/v1/organizations/settings`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          sandbox_provider: provider,
          timeout_minutes: Number(timeoutMinutes),
        }),
      });

      if (res.status === 403) {
        const payload = (await res.json().catch(() => null)) as {
          detail?: { code?: string; message?: string };
        } | null;
        const forbiddenDetail = extractOrgForbiddenDetail(payload);
        if (forbiddenDetail) {
          dispatchOrgForbiddenEvent(forbiddenDetail);
        }
        toast.error(
          payload?.detail?.message ||
            "Admin permission (org:admin) is required to save settings."
        );
        return;
      }

      if (!res.ok) {
        toast.error("Failed to save workspace configuration.");
        return;
      }

      toast.success("Workspace configuration saved successfully.");
    } catch {
      toast.error("Unable to reach agent engine to save configuration.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Workspace Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Configure execution sandboxes, resource timeouts, and security
          policies for this organization.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Sandbox Execution Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Cpu className="h-4 w-4 text-emerald-400" />
              Sandbox Execution Provider
            </CardTitle>
            <CardDescription className="text-xs">
              Select the compute environment used by autonomous workers to run
              untrusted agent code.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-medium text-foreground">
                Primary Execution Runtime
              </label>
              <Select value={provider} onValueChange={setProvider}>
                <SelectTrigger className="w-full sm:w-80">
                  <SelectValue placeholder="Select sandbox runtime" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="e2b">
                    E2B Firecracker microVM (Recommended)
                  </SelectItem>
                  <SelectItem value="docker">
                    Local Docker Engine (Fallback)
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[11px] text-muted-foreground">
                E2B creates isolated hardware virtual machines with dedicated
                kernel and memory boundaries.
              </p>
            </div>

            <div className="space-y-2 pt-2">
              <label className="text-xs font-medium text-foreground">
                Task Execution Timeout (Minutes)
              </label>
              <Input
                type="number"
                min="1"
                max="60"
                value={timeoutMinutes}
                onChange={(e) => setTimeoutMinutes(e.target.value)}
                className="w-full sm:w-40 font-mono"
              />
              <p className="text-[11px] text-muted-foreground">
                Tasks exceeding this runtime will be automatically terminated by
                the sandbox reaper.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Security and Credentials */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="h-4 w-4 text-purple-400" />
              Guardrails & Tenant Isolation
            </CardTitle>
            <CardDescription className="text-xs">
              Protected branch enforcement and tenant boundary settings.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-xs">
            <div className="flex items-center justify-between py-2 border-b border-border/50">
              <div>
                <div className="font-medium text-foreground">
                  Protected Branch Guard
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Prevent autonomous agents from pushing directly to main or
                  master branches.
                </div>
              </div>
              <span className="text-emerald-400 font-medium font-mono text-[11px]">
                Enforced
              </span>
            </div>

            <div className="flex items-center justify-between py-2">
              <div>
                <div className="font-medium text-foreground">
                  Database Trigger Immutability
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Audit log records are append only and protected from
                  alteration or deletion.
                </div>
              </div>
              <span className="text-emerald-400 font-medium font-mono text-[11px]">
                Active
              </span>
            </div>
          </CardContent>
          <CardFooter className="pt-2 border-t border-border flex justify-end">
            <Button
              type="submit"
              size="sm"
              disabled={isSaving}
              className="gap-1.5"
            >
              {isSaving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              <span>Save Changes</span>
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}

export function SettingsUnauthorizedView() {
  useBreadcrumbs([{ label: "Settings" }]);

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Workspace Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Organization administrator permissions are required for this view.
        </p>
      </div>

      <Card className="border-amber-500/40 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2 text-amber-400">
            <ShieldAlert className="h-4 w-4" />
            Admin Access Required
          </CardTitle>
          <CardDescription className="text-xs">
            Only members with the <code className="font-mono">org:admin</code>{" "}
            role can view or update sandbox runtime settings and organization
            guardrails.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          Ask an administrator in your Clerk organization to update your role or
          switch to an organization where you hold admin permissions.
        </CardContent>
        <CardFooter className="border-t border-border pt-4">
          <Button asChild variant="outline" size="sm" className="gap-1.5">
            <Link href="/tasks">
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>Back to Agent Tasks</span>
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
