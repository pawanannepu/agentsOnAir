import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  agentFetchJson,
  getAgentApiBaseUrl,
  resolveClientAuthToken,
  severityToneClass,
} from "../src/lib/review-api";
import { ORG_FORBIDDEN_EVENT } from "../src/lib/org-recovery";

describe("review-api client helpers (covers: AC-7)", () => {
  const originalEnv = process.env.NEXT_PUBLIC_AGENT_API_URL;

  beforeEach(() => {
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AGENT_API_URL;
    delete (window as unknown as { Clerk?: unknown }).Clerk;
  });

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.NEXT_PUBLIC_AGENT_API_URL;
    } else {
      process.env.NEXT_PUBLIC_AGENT_API_URL = originalEnv;
    }
    vi.unstubAllGlobals();
  });

  it("uses NEXT_PUBLIC_AGENT_API_URL when configured and defaults to localhost:8000", () => {
    expect(getAgentApiBaseUrl()).toBe("http://localhost:8000");
    process.env.NEXT_PUBLIC_AGENT_API_URL = "https://agent.example.com";
    expect(getAgentApiBaseUrl()).toBe("https://agent.example.com");
  });

  it("resolves auth token from explicit getter, Clerk window session, or null", async () => {
    await expect(resolveClientAuthToken()).resolves.toBeNull();

    (window as unknown as { Clerk?: unknown }).Clerk = {
      session: { getToken: vi.fn().mockResolvedValue("clerk-window-tok") },
    };
    await expect(resolveClientAuthToken()).resolves.toBe("clerk-window-tok");

    const explicitGetter = vi.fn().mockResolvedValue("explicit-tok");
    await expect(resolveClientAuthToken(explicitGetter)).resolves.toBe(
      "explicit-tok"
    );
  });

  it("sends JSON body with Authorization header and returns parsed data on 200", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "rule-1" }), { status: 200 })
      );
    vi.stubGlobal("fetch", fetchMock);

    const res = await agentFetchJson<{ id: string }>(
      "/api/v1/organizations/review-rules",
      {
        method: "POST",
        body: { title: "Check SQL" },
        token: "jwt-123",
      }
    );

    expect(res).toEqual({ ok: true, status: 200, data: { id: "rule-1" } });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/organizations/review-rules",
      {
        method: "POST",
        credentials: "include",
        headers: {
          Authorization: "Bearer jwt-123",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: "Check SQL" }),
      }
    );
  });

  it("returns ok with undefined data on 204 No Content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    );

    const res = await agentFetchJson<void>(
      "/api/v1/organizations/review-rules/1",
      {
        method: "DELETE",
        token: "jwt-123",
      }
    );

    expect(res).toEqual({ ok: true, status: 204, data: undefined });
  });

  it("dispatches org-forbidden event and extracts message on 403", async () => {
    const listener = vi.fn();
    window.addEventListener(ORG_FORBIDDEN_EVENT, listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: "org_inactive", message: "Org suspended" },
          }),
          { status: 403 }
        )
      )
    );

    const res = await agentFetchJson("/api/v1/analytics/overview");

    expect(res).toEqual({
      ok: false,
      status: 403,
      message: "Org suspended",
    });
    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual({
      code: "org_inactive",
      message: "Org suspended",
    });
    window.removeEventListener(ORG_FORBIDDEN_EVENT, listener);
  });

  it("parses string, array validation, and non-JSON error responses on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "Rule not found" }), {
            status: 404,
          })
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              detail: [{ msg: "path_globs must be non-empty" }],
            }),
            { status: 422 }
          )
        )
        .mockResolvedValueOnce(new Response("Gateway error", { status: 502 }))
    );

    expect(await agentFetchJson("/a")).toEqual({
      ok: false,
      status: 404,
      message: "Rule not found",
    });
    expect(await agentFetchJson("/b")).toEqual({
      ok: false,
      status: 422,
      message: "path_globs must be non-empty",
    });
    expect(await agentFetchJson("/c")).toEqual({
      ok: false,
      status: 502,
      message: "Request failed (502).",
    });
  });

  it("maps severity values to expected tone classes", () => {
    expect(severityToneClass("critical")).toContain("rose");
    expect(severityToneClass("major")).toContain("amber");
    expect(severityToneClass("minor")).toContain("sky");
    expect(severityToneClass("info")).toContain("zinc");
  });
});
