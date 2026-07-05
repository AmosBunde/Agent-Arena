import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ParetoRow } from "../types";
import { ParetoView } from "./ParetoView";

const FRONT: ParetoRow = {
  agent_id: "a",
  task_id: "t",
  provider: "openai",
  model: "cheap-strong",
  rubric_hash: "r",
  correct_count: 9,
  total_count: 10,
  accuracy: "0.9",
  mean_cost_usd: "0.010000",
  cost_per_correct_usd: "0.011111",
  on_front: true,
};

const DOMINATED: ParetoRow = {
  ...FRONT,
  model: "pricey-weak",
  correct_count: 5,
  accuracy: "0.5",
  mean_cost_usd: "0.050000",
  on_front: false,
};

vi.mock("../api", () => ({ api: { paretoFront: vi.fn() } }));

const { api } = await import("../api");
vi.mocked(api.paretoFront).mockResolvedValue([FRONT, DOMINATED]);

describe("ParetoView", () => {
  it("dims dominated rows and keeps front rows full strength", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ParetoView />
      </QueryClientProvider>,
    );
    const frontRow = (await screen.findByText("cheap-strong")).closest("tr");
    const dominatedRow = screen.getByText("pricey-weak").closest("tr");
    expect(frontRow).not.toHaveClass("dominated");
    expect(dominatedRow).toHaveClass("dominated");
    expect(screen.getByText("dominated")).toBeInTheDocument();
  });
});
