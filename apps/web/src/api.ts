// Thin typed client over the v1 API. The base URL is same-origin by
// default; the Vite dev server proxies /api to the local API service.

import type {
  Agent,
  LeaderboardRow,
  Run,
  RunCreateRequest,
  RunGroup,
  Rubric,
  Score,
  Task,
  TraceBody,
  TraceDetail,
  TraceMetadata,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body.detail !== undefined) detail = JSON.stringify(body.detail);
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  listTasks: () => request<Task[]>("/api/v1/tasks"),
  listAgents: () => request<Agent[]>("/api/v1/agents"),
  listRubrics: () => request<Rubric[]>("/api/v1/rubrics"),
  listRuns: (runGroupId?: string) =>
    request<Run[]>(
      runGroupId ? `/api/v1/runs?run_group_id=${encodeURIComponent(runGroupId)}` : "/api/v1/runs",
    ),
  createRuns: (payload: RunCreateRequest) =>
    request<RunGroup>("/api/v1/runs", { method: "POST", body: JSON.stringify(payload) }),
  cancelRun: (runId: string) =>
    request<{ id: string; status: string; detail: string }>(
      `/api/v1/runs/${encodeURIComponent(runId)}`,
      { method: "DELETE" },
    ),
  leaderboard: (refresh: boolean) =>
    request<LeaderboardRow[]>(`/api/v1/leaderboard${refresh ? "?refresh=true" : ""}`),
  listTraces: (runId?: string) =>
    request<TraceMetadata[]>(
      runId ? `/api/v1/traces?run_id=${encodeURIComponent(runId)}` : "/api/v1/traces",
    ),
  getTrace: (hash: string) => request<TraceDetail>(`/api/v1/traces/${encodeURIComponent(hash)}`),
  getTraceBody: (hash: string) =>
    request<TraceBody>(`/api/v1/traces/${encodeURIComponent(hash)}/body`),
  rescoreTrace: (hash: string, rubricId: string) =>
    request<Score>(`/api/v1/traces/${encodeURIComponent(hash)}/score`, {
      method: "POST",
      body: JSON.stringify({ rubric_id: rubricId }),
    }),
};
