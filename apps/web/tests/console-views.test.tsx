import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeAll, beforeEach } from "vitest";
import * as React from "react";
import { TasksView } from "../src/app/(console)/tasks/tasks-view";
import { TaskDetailClient } from "../src/app/(console)/tasks/[id]/task-detail-client";
import { RepositoriesView } from "../src/app/(console)/repositories/repositories-view";
import { SettingsView } from "../src/app/(console)/settings/settings-view";
import { Sidebar } from "../src/components/layout/sidebar";
import { Header } from "../src/components/layout/header";
import { BreadcrumbProvider } from "../src/components/layout/breadcrumb-context";
import { ConsoleLayout } from "../src/components/layout/console-layout";
import { toast } from "../src/components/ui/sonner";

vi.mock("../src/components/ui/sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
  Toaster: () => null,
}));

let currentPathname = "/tasks";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  window.Element.prototype.scrollIntoView = vi.fn();
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  currentPathname = "/tasks";
});

describe("TasksPage View (AC-2, AC-6)", () => {
  it("renders tasks header and initial task rows", () => {
    render(
      <BreadcrumbProvider>
        <TasksView />
      </BreadcrumbProvider>
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "Agent Tasks" })
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "feat(auth): integrate Clerk JWKS JWT verification in FastAPI"
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "fix(db): add partial unique index for soft deleted organizations"
      )
    ).toBeInTheDocument();
  });

  it("filters tasks by status tab", () => {
    render(
      <BreadcrumbProvider>
        <TasksView />
      </BreadcrumbProvider>
    );

    // Filter by 'Needs Review' (awaiting_approval)
    const reviewTab = screen.getByRole("tab", { name: /Needs Review/i });
    fireEvent.mouseDown(reviewTab);

    expect(
      screen.getByText(
        "review(pr): full repository AST context review on PR #42"
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "feat(auth): integrate Clerk JWKS JWT verification in FastAPI"
      )
    ).not.toBeInTheDocument();

    // Filter by 'Failed'
    const failedTab = screen.getByRole("tab", { name: "Failed" });
    fireEvent.mouseDown(failedTab);

    expect(
      screen.getByText(
        "test(e2e): verify sandbox recovery and checkpoint resumes"
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "review(pr): full repository AST context review on PR #42"
      )
    ).not.toBeInTheDocument();
  });

  it("filters tasks by text search and shows empty state when no match", () => {
    render(
      <BreadcrumbProvider>
        <TasksView />
      </BreadcrumbProvider>
    );

    const searchInput = screen.getByPlaceholderText(
      "Search by title, repo, or branch..."
    );
    fireEvent.change(searchInput, { target: { value: "langgraph" } });

    expect(
      screen.getByText(
        "chore(deps): update LangGraph and Langfuse trace exporter"
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "feat(auth): integrate Clerk JWKS JWT verification in FastAPI"
      )
    ).not.toBeInTheDocument();

    // Unmatched query
    fireEvent.change(searchInput, {
      target: { value: "nonexistent-query-12345" },
    });
    expect(
      screen.getByText("No agent tasks found matching your filter.")
    ).toBeInTheDocument();
  });
});

describe("TaskDetailClient View (AC-3, AC-4, AC-6)", () => {
  const sampleTaskId = "018f6c38-8921-7000-8000-000000000001";

  it("renders task metadata, status badge, and LangGraph node timeline", () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    expect(screen.getByText(sampleTaskId)).toBeInTheDocument();
    expect(screen.getByText("Task Metadata")).toBeInTheDocument();
    expect(screen.getByText("agentsOnAir/core")).toBeInTheDocument();
    expect(screen.getByText("feat/clerk-auth")).toBeInTheDocument();
    expect(screen.getByText("E2B (vm_01j982a)")).toBeInTheDocument();
    expect(screen.getByText("LangGraph Node Steps")).toBeInTheDocument();
    expect(screen.getByText("sandbox_allocate")).toBeInTheDocument();
    expect(screen.getByText("repo_checkout")).toBeInTheDocument();
    expect(screen.getByText("agent_execute")).toBeInTheDocument();
    expect(screen.getByText("code_review")).toBeInTheDocument();
  });

  it("triggers abort notification when Abort Task button is clicked", () => {
    render(
      <BreadcrumbProvider>
        <TaskDetailClient taskId={sampleTaskId} />
      </BreadcrumbProvider>
    );

    const abortButton = screen.getByRole("button", { name: /Abort Task/i });
    fireEvent.click(abortButton);

    expect(toast.error).toHaveBeenCalledWith(
      "Task execution aborted by operator."
    );
  });
});

describe("RepositoriesPage View (AC-6)", () => {
  it("renders connected repositories and badge states", () => {
    render(
      <BreadcrumbProvider>
        <RepositoriesView />
      </BreadcrumbProvider>
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "Connected Repositories" })
    ).toBeInTheDocument();
    expect(screen.getByText("core")).toBeInTheDocument();
    expect(screen.getByText("web-platform")).toBeInTheDocument();
    expect(screen.getByText("sandbox-templates")).toBeInTheDocument();
    expect(screen.getAllByText("Private").length).toBe(2);
    expect(screen.getByText("Public")).toBeInTheDocument();
  });
});

describe("SettingsPage View (AC-4, AC-6)", () => {
  it("renders workspace settings and handles form save", () => {
    render(
      <BreadcrumbProvider>
        <SettingsView />
      </BreadcrumbProvider>
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "Workspace Settings" })
    ).toBeInTheDocument();
    expect(screen.getByText("Sandbox Execution Provider")).toBeInTheDocument();

    const timeoutInput = screen.getByDisplayValue("10");
    fireEvent.change(timeoutInput, { target: { value: "15" } });
    expect(timeoutInput).toHaveValue(15);

    const saveButton = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveButton);

    expect(toast.success).toHaveBeenCalledWith(
      "Workspace configuration saved successfully."
    );
  });
});

describe("Console Shell Layout Components (AC-6)", () => {
  it("renders Sidebar navigation links and toggles collapse", () => {
    currentPathname = "/tasks";
    render(<Sidebar activeRunCount={2} />);

    expect(screen.getByText("agentsOnAir")).toBeInTheDocument();
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    expect(screen.getByText("Repositories")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument(); // active run badge

    const toggleButton = screen.getByTitle("Collapse sidebar");
    fireEvent.click(toggleButton);

    expect(document.cookie).toContain("aoa_sidebar_state=collapsed");
  });

  it("renders Header with dynamic breadcrumbs and search trigger", () => {
    const handleOpenCommand = vi.fn();
    render(
      <BreadcrumbProvider
        initialBreadcrumbs={[
          { label: "Tasks", href: "/tasks" },
          { label: "Detail" },
        ]}
      >
        <Header onOpenCommand={handleOpenCommand} isStreamActive={true} />
      </BreadcrumbProvider>
    );

    expect(screen.getByText("Console")).toBeInTheDocument();
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    expect(screen.getByText("Detail")).toBeInTheDocument();
    expect(screen.getByText("Live SSE")).toBeInTheDocument();

    const searchButton = screen.getByRole("button", { name: /Search/i });
    fireEvent.click(searchButton);
    expect(handleOpenCommand).toHaveBeenCalledTimes(1);
  });

  it("renders ConsoleLayout shell with children content", () => {
    render(
      <ConsoleLayout>
        <div data-testid="test-content">Dashboard Main Content</div>
      </ConsoleLayout>
    );

    expect(screen.getByTestId("test-content")).toBeInTheDocument();
  });
});
