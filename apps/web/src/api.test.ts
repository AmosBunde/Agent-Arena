import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./api";

function mockFetch(status: number, body: unknown) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  const spy = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("lists tasks from the v1 path", async () => {
    const spy = mockFetch(200, [{ id: "t1", slug: "word-problems-1" }]);
    const tasks = await api.listTasks();
    expect(spy).toHaveBeenCalledWith("/api/v1/tasks", expect.anything());
    expect(tasks[0]?.slug).toBe("word-problems-1");
  });

  it("posts run creation payloads as JSON", async () => {
    const spy = mockFetch(201, { run_group_id: "g1", runs: [] });
    await api.createRuns({
      task_id: "t",
      agent_id: "a",
      rubric_id: "r",
      providers: [{ provider: "openai", model: "gpt-4o-mini" }],
    });
    const [path, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string).providers).toHaveLength(1);
  });

  it("requests a leaderboard refresh through the query parameter", async () => {
    const spy = mockFetch(200, []);
    await api.leaderboard(true);
    expect(spy).toHaveBeenCalledWith("/api/v1/leaderboard?refresh=true", expect.anything());
  });

  it("surfaces error details as ApiError", async () => {
    mockFetch(403, { detail: "role 'viewer' may not perform this operation" });
    await expect(api.leaderboard(true)).rejects.toBeInstanceOf(ApiError);
  });
});
