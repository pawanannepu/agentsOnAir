import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as React from "react";
import {
  BreadcrumbProvider,
  useBreadcrumbs,
} from "../src/components/layout/breadcrumb-context";

describe("useBreadcrumbs hook regression", () => {
  it("does not cause infinite update loop when given new array references with same content", () => {
    let renderCount = 0;

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <BreadcrumbProvider>{children}</BreadcrumbProvider>
    );

    const { result, rerender } = renderHook(
      ({ items }) => {
        renderCount++;
        return useBreadcrumbs(items);
      },
      {
        wrapper,
        initialProps: { items: [{ label: "Repositories" }] },
      }
    );

    expect(result.current.breadcrumbs).toEqual([{ label: "Repositories" }]);

    // Rerender with a brand new array reference with identical content
    act(() => {
      rerender({ items: [{ label: "Repositories" }] });
    });

    expect(result.current.breadcrumbs).toEqual([{ label: "Repositories" }]);
    // Render count should be stable (initial mount + effect update + 1 rerender), definitely not 50+
    expect(renderCount).toBeLessThan(5);
  });
});
