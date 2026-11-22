"use client";

import * as React from "react";
import { Cpu, Shield, Save } from "lucide-react";
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

export default function SettingsPage() {
  const [provider, setProvider] = React.useState("e2b");
  const [timeoutMinutes, setTimeoutMinutes] = React.useState("10");

  useBreadcrumbs([{ label: "Settings" }]);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    toast.success("Workspace configuration saved successfully.");
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
            <Button type="submit" size="sm" className="gap-1.5">
              <Save className="h-3.5 w-3.5" />
              <span>Save Changes</span>
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}
