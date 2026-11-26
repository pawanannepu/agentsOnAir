"use client";

import * as React from "react";
import {
  FolderGit2,
  PlusCircle,
  ExternalLink,
  GitBranch,
  Lock,
  Globe,
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
import { Badge } from "@/components/ui/badge";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";

interface Repository {
  id: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  isPrivate: boolean;
  activeTasks: number;
  lastSynced: string;
}

const mockRepositories: Repository[] = [
  {
    id: "repo_01",
    name: "core",
    fullName: "agentsOnAir/core",
    defaultBranch: "main",
    isPrivate: true,
    activeTasks: 1,
    lastSynced: "2 minutes ago",
  },
  {
    id: "repo_02",
    name: "web-platform",
    fullName: "acme/web-platform",
    defaultBranch: "main",
    isPrivate: true,
    activeTasks: 1,
    lastSynced: "1 hour ago",
  },
  {
    id: "repo_03",
    name: "sandbox-templates",
    fullName: "agentsOnAir/sandbox-templates",
    defaultBranch: "main",
    isPrivate: false,
    activeTasks: 0,
    lastSynced: "Yesterday",
  },
];

export function RepositoriesView() {
  useBreadcrumbs([{ label: "Repositories" }]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Connected Repositories
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Repositories authorized via the agentsOnAir GitHub App for automated
            task runs and code reviews.
          </p>
        </div>
        <Button size="sm" className="gap-1.5 shrink-0">
          <PlusCircle className="h-4 w-4" />
          <span>Connect Repository</span>
        </Button>
      </div>

      {/* Repositories Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {mockRepositories.map((repo) => (
          <Card key={repo.id} className="flex flex-col justify-between">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FolderGit2 className="h-4 w-4 text-blue-400 shrink-0" />
                  <CardTitle className="text-base truncate">
                    {repo.name}
                  </CardTitle>
                </div>
                <div className="flex items-center gap-1.5">
                  {repo.isPrivate ? (
                    <span className="flex items-center gap-1 text-[11px] text-zinc-400 font-mono px-2 py-0.5 rounded bg-zinc-800">
                      <Lock className="h-3 w-3" />
                      Private
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[11px] text-zinc-400 font-mono px-2 py-0.5 rounded bg-zinc-800">
                      <Globe className="h-3 w-3" />
                      Public
                    </span>
                  )}
                </div>
              </div>
              <CardDescription className="text-xs font-mono">
                {repo.fullName}
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground flex items-center gap-1">
                  <GitBranch className="h-3.5 w-3.5" />
                  Default Branch
                </span>
                <span className="font-mono font-medium text-foreground">
                  {repo.defaultBranch}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-border/50">
                <span className="text-muted-foreground">Active Tasks</span>
                <span className="font-mono font-medium">
                  {repo.activeTasks > 0 ? (
                    <Badge variant="running" pulse>
                      {repo.activeTasks} active
                    </Badge>
                  ) : (
                    <span className="text-zinc-500">Idle</span>
                  )}
                </span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">Last Sync</span>
                <span className="text-muted-foreground">{repo.lastSynced}</span>
              </div>
            </CardContent>

            <CardFooter className="pt-2 border-t border-border/50 flex justify-between">
              <Button
                asChild
                variant="outline"
                size="sm"
                className="w-full text-xs"
              >
                <a
                  href={`https://github.com/${repo.fullName}`}
                  target="_blank"
                  rel="noreferrer"
                  className="gap-1.5"
                >
                  <span>Open on GitHub</span>
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
}
