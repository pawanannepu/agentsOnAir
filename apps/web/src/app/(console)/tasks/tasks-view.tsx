"use client";

import * as React from "react";
import Link from "next/link";
import { PlusCircle, ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBreadcrumbs } from "@/components/layout/breadcrumb-context";

interface TaskItem {
  id: string;
  title: string;
  repo: string;
  branch: string;
  status:
    | "queued"
    | "running"
    | "awaiting_approval"
    | "succeeded"
    | "failed"
    | "cancelled";
  duration: string;
  createdAt: string;
  author: string;
}

const initialTasks: TaskItem[] = [
  {
    id: "018f6c38-8921-7000-8000-000000000001",
    title: "feat(auth): integrate Clerk JWKS JWT verification in FastAPI",
    repo: "agentsOnAir/core",
    branch: "feat/clerk-auth",
    status: "running",
    duration: "2m 14s",
    createdAt: "Just now",
    author: "autonomous-forge",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000002",
    title: "fix(db): add partial unique index for soft deleted organizations",
    repo: "agentsOnAir/core",
    branch: "fix/org-index",
    status: "succeeded",
    duration: "4m 32s",
    createdAt: "12m ago",
    author: "autonomous-forge",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000003",
    title: "review(pr): full repository AST context review on PR #42",
    repo: "acme/web-platform",
    branch: "refactor/payment-flow",
    status: "awaiting_approval",
    duration: "1m 45s",
    createdAt: "35m ago",
    author: "independent-reviewer",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000004",
    title: "chore(deps): update LangGraph and Langfuse trace exporter",
    repo: "agentsOnAir/core",
    branch: "chore/langgraph-v0.2",
    status: "succeeded",
    duration: "3m 10s",
    createdAt: "2h ago",
    author: "autonomous-forge",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000005",
    title: "test(e2e): verify sandbox recovery and checkpoint resumes",
    repo: "agentsOnAir/core",
    branch: "test/checkpoint-recovery",
    status: "failed",
    duration: "8m 04s",
    createdAt: "4h ago",
    author: "autonomous-forge",
  },
];

export function TasksView() {
  const [filterTab, setFilterTab] = React.useState<string>("all");
  const [search, setSearch] = React.useState("");

  useBreadcrumbs([{ label: "Tasks" }]);

  const filteredTasks = React.useMemo(() => {
    return initialTasks.filter((task) => {
      const matchesTab =
        filterTab === "all" ||
        (filterTab === "running" && task.status === "running") ||
        (filterTab === "awaiting" && task.status === "awaiting_approval") ||
        (filterTab === "succeeded" && task.status === "succeeded") ||
        (filterTab === "failed" && task.status === "failed");

      const matchesSearch =
        search === "" ||
        task.title.toLowerCase().includes(search.toLowerCase()) ||
        task.repo.toLowerCase().includes(search.toLowerCase()) ||
        task.branch.toLowerCase().includes(search.toLowerCase());

      return matchesTab && matchesSearch;
    });
  }, [filterTab, search]);

  return (
    <div className="space-y-6">
      {/* Header with Title and Create Button */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Agent Tasks
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Monitor autonomous tasks, sandbox runs, and review statuses across
            all connected repositories.
          </p>
        </div>
        <Button size="sm" className="gap-1.5 shrink-0">
          <PlusCircle className="h-4 w-4" />
          <span>New Task</span>
        </Button>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
        <Tabs value={filterTab} onValueChange={setFilterTab}>
          <TabsList className="bg-muted/60">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="running" className="gap-1.5">
              <span>Running</span>
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </TabsTrigger>
            <TabsTrigger value="awaiting">Needs Review</TabsTrigger>
            <TabsTrigger value="succeeded">Succeeded</TabsTrigger>
            <TabsTrigger value="failed">Failed</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="relative w-full sm:w-72">
          <Input
            placeholder="Search by title, repo, or branch..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 text-xs"
          />
        </div>
      </div>

      {/* Tasks Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">Status</TableHead>
              <TableHead>Task Title</TableHead>
              <TableHead className="hidden md:table-cell">Repository</TableHead>
              <TableHead className="hidden lg:table-cell">Branch</TableHead>
              <TableHead className="hidden sm:table-cell">Duration</TableHead>
              <TableHead className="text-right">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredTasks.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="h-32 text-center text-muted-foreground"
                >
                  No agent tasks found matching your filter.
                </TableCell>
              </TableRow>
            ) : (
              filteredTasks.map((task) => (
                <TableRow key={task.id} className="group cursor-pointer">
                  <TableCell>
                    <Badge
                      variant={task.status}
                      pulse={task.status === "running"}
                    >
                      {task.status.replace("_", " ")}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium text-foreground">
                    <Link
                      href={`/tasks/${task.id}`}
                      className="flex items-center gap-1.5 hover:text-emerald-400 transition-colors"
                    >
                      <span className="truncate max-w-md">{task.title}</span>
                      <ArrowUpRight className="h-3.5 w-3.5 opacity-0 group-hover:opacity-100 transition-opacity text-emerald-400 shrink-0" />
                    </Link>
                  </TableCell>
                  <TableCell className="hidden md:table-cell font-mono text-xs text-muted-foreground">
                    {task.repo}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell font-mono text-xs text-muted-foreground">
                    {task.branch}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell font-mono text-xs text-muted-foreground">
                    {task.duration}
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">
                    {task.createdAt}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
