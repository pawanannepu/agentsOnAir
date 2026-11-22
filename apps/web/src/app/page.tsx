import Link from "next/link";
import {
  FolderGit2,
  PlusCircle,
  Play,
  CheckCircle2,
  Clock,
  ArrowRight,
  Cpu,
  Layers,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const mockRecentTasks = [
  {
    id: "018f6c38-8921-7000-8000-000000000001",
    title: "feat(auth): integrate Clerk JWKS JWT verification in FastAPI",
    repo: "agentsOnAir/core",
    branch: "feat/clerk-auth",
    status: "running" as const,
    duration: "2m 14s",
    createdAt: "Just now",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000002",
    title: "fix(db): add partial unique index for soft deleted organizations",
    repo: "agentsOnAir/core",
    branch: "fix/org-index",
    status: "succeeded" as const,
    duration: "4m 32s",
    createdAt: "12m ago",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000003",
    title: "review(pr): full repository AST context review on PR #42",
    repo: "acme/web-platform",
    branch: "refactor/payment-flow",
    status: "awaiting_approval" as const,
    duration: "1m 45s",
    createdAt: "35m ago",
  },
  {
    id: "018f6c38-8921-7000-8000-000000000004",
    title: "chore(deps): update LangGraph and Langfuse trace exporter",
    repo: "agentsOnAir/core",
    branch: "chore/langgraph-v0.2",
    status: "succeeded" as const,
    duration: "3m 10s",
    createdAt: "2h ago",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-8">
      {/* Top Welcome and Quick Action Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Developer Mission Control
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Autonomous engineering, test execution, and code review in isolated
            microVM sandboxes.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild variant="outline" size="sm">
            <Link href="/repositories">
              <FolderGit2 className="h-4 w-4 mr-1.5" />
              Manage Repos
            </Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/tasks">
              <PlusCircle className="h-4 w-4 mr-1.5" />
              New Task
            </Link>
          </Button>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Active Agent Tasks
            </CardTitle>
            <Play className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">1</div>
            <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Running in E2B microVM
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Awaiting Review
            </CardTitle>
            <Clock className="h-4 w-4 text-amber-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">1</div>
            <p className="text-xs text-muted-foreground mt-1">
              Ready for human approval
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Verified Pull Requests
            </CardTitle>
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">24</div>
            <p className="text-xs text-emerald-400 mt-1 font-medium">
              100% test pass rate
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Connected Repos
            </CardTitle>
            <FolderGit2 className="h-4 w-4 text-blue-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">3</div>
            <p className="text-xs text-muted-foreground mt-1">
              GitHub App installed
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Main Content: Recent Tasks & System Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Tasks List */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight text-foreground">
              Recent Execution Tasks
            </h2>
            <Link
              href="/tasks"
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
            >
              View all tasks
              <ArrowRight className="h-3 w-3" />
            </Link>
          </div>

          <div className="divide-y divide-border rounded-xl border border-border bg-card overflow-hidden">
            {mockRecentTasks.map((task) => (
              <Link
                key={task.id}
                href={`/tasks/${task.id}`}
                className="flex flex-col sm:flex-row sm:items-center justify-between p-4 hover:bg-muted/50 transition-colors gap-3"
              >
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={task.status}
                      pulse={task.status === "running"}
                    >
                      {task.status.replace("_", " ")}
                    </Badge>
                    <span className="text-xs text-muted-foreground font-mono">
                      {task.repo}
                    </span>
                  </div>
                  <h3 className="text-sm font-medium text-foreground truncate">
                    {task.title}
                  </h3>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground font-mono">
                    <span>branch: {task.branch}</span>
                    <span>•</span>
                    <span>duration: {task.duration}</span>
                  </div>
                </div>

                <div className="text-xs text-muted-foreground sm:text-right shrink-0">
                  {task.createdAt}
                </div>
              </Link>
            ))}
          </div>
        </div>

        {/* System Architecture and Sandboxes Panel */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold tracking-tight text-foreground">
            Platform Infrastructure
          </h2>

          <div className="space-y-3">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-emerald-400" />
                  Sandbox Execution Runtime
                </CardTitle>
                <CardDescription className="text-xs">
                  Isolated microVM environment with hardware boundary.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-border/50">
                  <span className="text-muted-foreground">
                    Primary Provider
                  </span>
                  <span className="font-mono font-medium text-foreground">
                    E2B Firecracker microVM
                  </span>
                </div>
                <div className="flex justify-between py-1 border-b border-border/50">
                  <span className="text-muted-foreground">Local Fallback</span>
                  <span className="font-mono font-medium text-foreground">
                    Docker Engine
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-muted-foreground">Timeout Cap</span>
                  <span className="font-mono text-foreground">10 minutes</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Layers className="h-4 w-4 text-blue-400" />
                  Engine Services
                </CardTitle>
                <CardDescription className="text-xs">
                  FastAPI service with LangGraph & Redis Pub/Sub.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-border/50">
                  <span className="text-muted-foreground">FastAPI Engine</span>
                  <span className="text-emerald-400 font-mono font-medium flex items-center gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    Online (port 8000)
                  </span>
                </div>
                <div className="flex justify-between py-1 border-b border-border/50">
                  <span className="text-muted-foreground">Persistence</span>
                  <span className="font-mono text-foreground">
                    PostgreSQL 16 (UUIDv7)
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-muted-foreground">Queue Broker</span>
                  <span className="font-mono text-foreground">
                    Redis 7 (ARQ Workers)
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
