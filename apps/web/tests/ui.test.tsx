import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { Button } from "../src/components/ui/button";
import { Badge } from "../src/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "../src/components/ui/card";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "../src/components/ui/table";
import { TerminalViewer } from "../src/components/ui/terminal-viewer";
import { Input, Textarea } from "../src/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../src/components/ui/dialog";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "../src/components/ui/tabs";
import {
  Select,
  SelectTrigger,
  SelectValue,
} from "../src/components/ui/select";
import { cn } from "../src/lib/utils";

// Mock router
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
  usePathname: () => "/tasks",
}));

describe("UI Foundation Primitives (AC-2)", () => {
  describe("Button component", () => {
    it("renders default button with accessible text", () => {
      render(<Button>Run Task</Button>);
      const button = screen.getByRole("button", { name: "Run Task" });
      expect(button).toBeInTheDocument();
      expect(button).not.toBeDisabled();
    });

    it("renders destructive variant and disabled state", () => {
      render(
        <Button variant="destructive" disabled>
          Abort Run
        </Button>
      );
      const button = screen.getByRole("button", { name: "Abort Run" });
      expect(button).toBeDisabled();
    });
  });

  describe("Badge component", () => {
    it("renders status variants aligned with database enums", () => {
      const { rerender } = render(<Badge variant="running">Running</Badge>);
      expect(screen.getByText("Running")).toBeInTheDocument();

      rerender(<Badge variant="succeeded">Succeeded</Badge>);
      expect(screen.getByText("Succeeded")).toBeInTheDocument();

      rerender(<Badge variant="failed">Failed</Badge>);
      expect(screen.getByText("Failed")).toBeInTheDocument();

      rerender(<Badge variant="queued">Queued</Badge>);
      expect(screen.getByText("Queued")).toBeInTheDocument();
    });

    it("renders pulsing indicator dot when pulse is true", () => {
      const { container } = render(
        <Badge variant="running" pulse>
          Live Run
        </Badge>
      );
      const ping = container.querySelector(".animate-ping");
      expect(ping).toBeInTheDocument();
    });
  });

  describe("Card component", () => {
    it("renders card with title and content", () => {
      render(
        <Card>
          <CardHeader>
            <CardTitle>Sandbox Isolation</CardTitle>
          </CardHeader>
          <CardContent>E2B microVM</CardContent>
        </Card>
      );
      expect(screen.getByText("Sandbox Isolation")).toBeInTheDocument();
      expect(screen.getByText("E2B microVM")).toBeInTheDocument();
    });
  });

  describe("Table component", () => {
    it("renders structured table with headers and cells", () => {
      render(
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Task</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>Linting</TableCell>
              <TableCell>Completed</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      );

      expect(screen.getByText("Task")).toBeInTheDocument();
      expect(screen.getByText("Linting")).toBeInTheDocument();
      expect(screen.getByText("Completed")).toBeInTheDocument();
    });
  });

  describe("Input and Textarea components", () => {
    it("handles text input changes and disabled state", () => {
      const handleChange = vi.fn();
      render(
        <Input
          placeholder="Task title"
          onChange={handleChange}
          aria-label="Task title"
        />
      );

      const input = screen.getByLabelText("Task title");
      expect(input).toBeInTheDocument();

      fireEvent.change(input, { target: { value: "feat: new feature" } });
      expect(handleChange).toHaveBeenCalled();
    });

    it("renders textarea with placeholder", () => {
      render(
        <Textarea placeholder="Enter description" aria-label="Description" />
      );
      expect(screen.getByLabelText("Description")).toBeInTheDocument();
    });
  });

  describe("Dialog component", () => {
    it("opens dialog modal when trigger is clicked", () => {
      render(
        <Dialog>
          <DialogTrigger asChild>
            <Button>Open Dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Confirm Action</DialogTitle>
              <DialogDescription>
                Are you sure you want to proceed?
              </DialogDescription>
            </DialogHeader>
          </DialogContent>
        </Dialog>
      );

      expect(screen.queryByText("Confirm Action")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Open Dialog" }));
      expect(screen.getByText("Confirm Action")).toBeInTheDocument();
      expect(
        screen.getByText("Are you sure you want to proceed?")
      ).toBeInTheDocument();
    });
  });

  describe("Tabs component", () => {
    it("switches active tab content on tab trigger click", () => {
      render(
        <Tabs defaultValue="all">
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="running">Running</TabsTrigger>
          </TabsList>
          <TabsContent value="all">All tasks content</TabsContent>
          <TabsContent value="running">Running tasks content</TabsContent>
        </Tabs>
      );

      expect(screen.getByText("All tasks content")).toBeInTheDocument();
      expect(
        screen.queryByText("Running tasks content")
      ).not.toBeInTheDocument();

      const runningTab = screen.getByRole("tab", { name: "Running" });
      fireEvent.mouseDown(runningTab);
      expect(screen.getByText("Running tasks content")).toBeInTheDocument();
      expect(screen.queryByText("All tasks content")).not.toBeInTheDocument();
    });
  });

  describe("Select component", () => {
    it("renders select trigger with placeholder", () => {
      render(
        <Select>
          <SelectTrigger aria-label="Select Runtime">
            <SelectValue placeholder="Choose provider" />
          </SelectTrigger>
        </Select>
      );

      expect(screen.getByLabelText("Select Runtime")).toBeInTheDocument();
      expect(screen.getByText("Choose provider")).toBeInTheDocument();
    });
  });

  describe("cn utility helper (AC-1)", () => {
    it("merges classes and resolves Tailwind conflicts correctly", () => {
      const result = cn("px-2 py-1", "px-4", undefined, false && "hidden");
      expect(result).toBe("py-1 px-4");
    });
  });
});

describe("TerminalViewer Component (AC-3)", () => {
  const sampleLogs = [
    "Allocating sandbox container...",
    "Running pytest tests/test_auth.py",
    "PASSED 4 of 4 tests",
  ];

  it("renders terminal logs and line count", () => {
    render(
      <TerminalViewer logs={sampleLogs} isStreaming title="Test Runner" />
    );

    expect(screen.getByText("Test Runner")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText(/Showing 3 lines/)).toBeInTheDocument();
  });

  it("filters log lines when search query is entered", () => {
    render(<TerminalViewer logs={sampleLogs} />);

    const searchInput = screen.getByPlaceholderText("Search logs...");
    fireEvent.change(searchInput, { target: { value: "pytest" } });

    expect(screen.getByText(/filtered from 3/)).toBeInTheDocument();
  });

  it("copies clean plain text on copy button click", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<TerminalViewer logs={sampleLogs} />);

    const copyBtn = screen.getByTitle("Copy clean log lines");
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextMock).toHaveBeenCalledWith(sampleLogs.join("\n"));
  });
});
