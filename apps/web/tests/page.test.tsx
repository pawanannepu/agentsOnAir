import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HomeView as HomePage } from "../src/app/(console)/home-view";

describe("HomePage console overview component (AC-1, AC-6)", () => {
  it("renders mission control heading and platform description", () => {
    render(<HomePage />);

    const heading = screen.getByRole("heading", {
      level: 1,
      name: /Developer Mission Control/i,
    });
    expect(heading).toBeInTheDocument();

    expect(
      screen.getByText(
        /Autonomous engineering, test execution, and code review in isolated microVM sandboxes/i
      )
    ).toBeInTheDocument();
  });

  it("renders metric cards for active tasks, reviews, and connected repos", () => {
    render(<HomePage />);

    expect(screen.getByText("Active Agent Tasks")).toBeInTheDocument();
    expect(screen.getByText("Awaiting Review")).toBeInTheDocument();
    expect(screen.getByText("Verified Pull Requests")).toBeInTheDocument();
    expect(screen.getByText("Connected Repos")).toBeInTheDocument();
  });

  it("renders recent execution tasks list with links", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", { level: 2, name: /Recent Execution Tasks/i })
    ).toBeInTheDocument();

    expect(
      screen.getByText(/integrate Clerk JWKS JWT verification/i)
    ).toBeInTheDocument();
  });

  it("renders platform infrastructure architecture cards", () => {
    render(<HomePage />);

    expect(screen.getByText("Sandbox Execution Runtime")).toBeInTheDocument();
    expect(screen.getByText("Engine Services")).toBeInTheDocument();
  });
});
