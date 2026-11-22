import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeAll, beforeEach } from "vitest";
import * as React from "react";
import { CommandDialog } from "../src/components/ui/command-dialog";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
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
  mockPush.mockClear();
  localStorage.clear();
});

describe("CommandDialog Component (AC-5)", () => {
  it("navigates to /repositories when Connected Repositories is selected", () => {
    const onOpenChange = vi.fn();
    render(<CommandDialog open={true} onOpenChange={onOpenChange} />);

    const repoItem = screen.getByText("Connected Repositories");
    expect(repoItem).toBeInTheDocument();

    fireEvent.click(repoItem);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mockPush).toHaveBeenCalledWith("/repositories");
  });

  it("navigates to /tasks when All Tasks is selected", () => {
    const onOpenChange = vi.fn();
    render(<CommandDialog open={true} onOpenChange={onOpenChange} />);

    const tasksItem = screen.getByText("All Tasks");
    expect(tasksItem).toBeInTheDocument();

    fireEvent.click(tasksItem);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mockPush).toHaveBeenCalledWith("/tasks");
  });

  it("navigates to /settings when Workspace Settings is selected", () => {
    const onOpenChange = vi.fn();
    render(<CommandDialog open={true} onOpenChange={onOpenChange} />);

    const settingsItem = screen.getByText("Workspace Settings");
    expect(settingsItem).toBeInTheDocument();

    fireEvent.click(settingsItem);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mockPush).toHaveBeenCalledWith("/settings");
  });

  it("navigates to /tasks when Create New Task is selected", () => {
    const onOpenChange = vi.fn();
    render(<CommandDialog open={true} onOpenChange={onOpenChange} />);

    const createItem = screen.getByText("Create New Task");
    expect(createItem).toBeInTheDocument();

    fireEvent.click(createItem);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mockPush).toHaveBeenCalledWith("/tasks");
  });

  it("toggles open state on Cmd+K or Ctrl+K shortcut", () => {
    const onOpenChange = vi.fn();
    render(<CommandDialog open={false} onOpenChange={onOpenChange} />);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("renders cached recent tasks from localStorage and navigates on select", () => {
    const sampleRecent = [
      {
        id: "task_123",
        title: "fix(sandbox): network isolation rule",
        repo: "agentsOnAir/core",
      },
    ];
    localStorage.setItem("aoa_recent_tasks", JSON.stringify(sampleRecent));

    const onOpenChange = vi.fn();
    render(<CommandDialog open={true} onOpenChange={onOpenChange} />);

    expect(screen.getByText("Recent Tasks")).toBeInTheDocument();
    const taskItem = screen.getByText("fix(sandbox): network isolation rule");
    expect(taskItem).toBeInTheDocument();

    fireEvent.click(taskItem);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mockPush).toHaveBeenCalledWith("/tasks/task_123");
  });
});
