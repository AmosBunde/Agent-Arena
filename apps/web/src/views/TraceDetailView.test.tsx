import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TraceBody, TraceDetail } from "../types";
import { TraceDetailView } from "./TraceDetailView";

const HASH = "abc123def4567890";

const DETAIL: TraceDetail = {
  hash: HASH,
  run_id: "r1",
  attempt_id: "a1",
  body_uri: "file:///traces/ab.json",
  body_size_bytes: 512,
  total_input_tokens: 110,
  total_output_tokens: 25,
  total_cached_tokens: 0,
  estimated_cost_usd: "0.000135",
  latency_ms: 350,
  tool_call_count: 1,
  created_at: "2026-07-06T00:00:00Z",
  scores: [
    {
      trace_hash: HASH,
      rubric_hash: "rubric-hash-1",
      score: "1.0000",
      is_correct: true,
      score_detail: {},
      judge_model: null,
      scored_at: "2026-07-06T00:01:00Z",
    },
  ],
};

const BODY: TraceBody = {
  schema_version: 1,
  run_id: "r1",
  attempt_number: 1,
  provider: "fake",
  model: "fake-model",
  parameters: { temperature: 0, tools: ["calculator"] },
  task: { slug: "calculator-1", version: "1" },
  agent: { slug: "baseline", version: "1" },
  steps: [
    {
      index: 0,
      request_messages: [
        { role: "user", content: "compute 6 * 7", tool_calls: [], tool_call_id: null, name: null },
      ],
      response: {
        content: null,
        finish_reason: "tool_use",
        tool_calls: [{ id: "c1", name: "calculator", arguments: { expression: "6 * 7" } }],
        usage: { prompt_tokens: 100, completion_tokens: 20, cached_tokens: 0 },
        latency_ms: 200,
        provider_metadata: {},
      },
      tool_results: [{ tool_call_id: "c1", name: "calculator", output: "42" }],
    },
    {
      index: 1,
      request_messages: [],
      response: {
        content: "42",
        finish_reason: "stop",
        tool_calls: [],
        usage: { prompt_tokens: 10, completion_tokens: 5, cached_tokens: 0 },
        latency_ms: 150,
        provider_metadata: {},
      },
      tool_results: [],
    },
  ],
  final_answer: "42",
  turn_limit_reached: false,
  error: null,
  totals: {
    prompt_tokens: 110,
    completion_tokens: 25,
    cached_tokens: 0,
    latency_ms: 350,
    tool_call_count: 1,
  },
};

vi.mock("../api", () => ({
  api: {
    getTrace: vi.fn(),
    getTraceBody: vi.fn(),
    listRubrics: vi.fn(),
    rescoreTrace: vi.fn(),
  },
}));

const { api } = await import("../api");
vi.mocked(api.getTrace).mockResolvedValue(DETAIL);
vi.mocked(api.getTraceBody).mockResolvedValue(BODY);
vi.mocked(api.listRubrics).mockResolvedValue([]);

describe("TraceDetailView", () => {
  it("renders metadata, scores, and the tool call timeline", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TraceDetailView hash={HASH} onBack={() => {}} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("$0.000135")).toBeInTheDocument();
    expect(screen.getByText(/Turn 1: 100 in \/ 20 out tokens, 200 ms/)).toBeInTheDocument();
    expect(screen.getByText(/calculator result:/)).toBeInTheDocument();
    expect(screen.getByText("Re-score")).toBeInTheDocument();
    expect(screen.getByText("yes")).toBeInTheDocument();
  });
});
