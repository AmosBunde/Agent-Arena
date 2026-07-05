import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LeaderboardRow } from "../types";
import { LeaderboardView } from "./LeaderboardView";

const ROW: LeaderboardRow = {
  agent_id: "a",
  task_id: "t",
  provider: "openai",
  model: "gpt-4o-mini",
  rubric_hash: "r",
  correct_count: 2,
  total_count: 3,
  mean_score: "0.6667",
  total_cost_usd: "0.030000",
  cost_per_correct_usd: "0.015000",
  p50_latency_ms: 120,
  p95_latency_ms: 250,
};

const ZERO_CORRECT: LeaderboardRow = {
  ...ROW,
  model: "wrong-model",
  correct_count: 0,
  cost_per_correct_usd: null,
};

vi.mock("../api", () => ({
  api: { leaderboard: vi.fn() },
}));

const { api } = await import("../api");
vi.mocked(api.leaderboard).mockResolvedValue([ROW, ZERO_CORRECT]);

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LeaderboardView />
    </QueryClientProvider>,
  );
}

describe("LeaderboardView", () => {
  it("renders CPCA and shows zero-correct groups without a number", async () => {
    renderView();
    expect(await screen.findByText("$0.015000")).toBeInTheDocument();
    expect(screen.getByText("no correct answers")).toBeInTheDocument();
    expect(screen.getByText("2/3")).toBeInTheDocument();
  });
});
