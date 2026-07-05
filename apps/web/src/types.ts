// Mirrors apps/api/schemas.py. Decimal fields arrive as JSON strings.

export interface Task {
  id: string;
  slug: string;
  version: string;
  domain: string;
  definition: Record<string, unknown>;
  capabilities_required: string[];
  created_at: string;
  deprecated_at: string | null;
}

export interface Rubric {
  id: string;
  slug: string;
  version: string;
  definition_hash: string;
  definition: Record<string, unknown>;
  judge_required: boolean;
  created_at: string;
}

export interface Agent {
  id: string;
  slug: string;
  version: string;
  definition: Record<string, unknown>;
  created_at: string;
}

export interface Run {
  id: string;
  run_group_id: string | null;
  agent_id: string;
  task_id: string;
  provider: string;
  model: string;
  rubric_id: string;
  status: string;
  failure_reason: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_by: string;
}

export interface RunGroup {
  run_group_id: string;
  runs: Run[];
}

export interface ProviderModel {
  provider: string;
  model: string;
}

export interface RunCreateRequest {
  agent_id: string;
  task_id: string;
  rubric_id: string;
  providers: ProviderModel[];
  run_group_name?: string;
}

export interface LeaderboardRow {
  agent_id: string;
  task_id: string;
  provider: string;
  model: string;
  rubric_hash: string;
  correct_count: number;
  total_count: number;
  mean_score: string;
  total_cost_usd: string;
  cost_per_correct_usd: string | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  accuracy_ci_low: string | null;
  accuracy_ci_high: string | null;
  cpca_ci_low_usd: string | null;
  cpca_ci_high_usd: string | null;
  ci_resamples: number | null;
}

export interface TraceMetadata {
  hash: string;
  run_id: string;
  attempt_id: string;
  body_uri: string | null;
  body_size_bytes: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cached_tokens: number;
  estimated_cost_usd: string;
  latency_ms: number;
  tool_call_count: number;
  created_at: string;
}

export interface Score {
  trace_hash: string;
  rubric_hash: string;
  score: string;
  is_correct: boolean;
  score_detail: Record<string, unknown>;
  judge_model: string | null;
  scored_at: string;
}

export interface TraceDetail extends TraceMetadata {
  scores: Score[];
}

export interface TraceToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface TraceMessage {
  role: string;
  content: string | null;
  tool_calls: TraceToolCall[];
  tool_call_id: string | null;
  name: string | null;
}

export interface TraceStep {
  index: number;
  request_messages: TraceMessage[];
  response: {
    content: string | null;
    finish_reason: string | null;
    tool_calls: TraceToolCall[];
    usage: { prompt_tokens: number; completion_tokens: number; cached_tokens: number };
    latency_ms: number;
    provider_metadata: Record<string, unknown>;
  };
  tool_results: { tool_call_id: string; name: string; output: string }[];
}

export interface TraceBody {
  schema_version: number;
  run_id: string;
  attempt_number: number;
  provider: string;
  model: string;
  parameters: { temperature: number | null; tools: string[] };
  task: { slug: string; version: string };
  agent: { slug: string; version: string };
  steps: TraceStep[];
  final_answer: string | null;
  turn_limit_reached: boolean;
  error: string | null;
  totals: {
    prompt_tokens: number;
    completion_tokens: number;
    cached_tokens: number;
    latency_ms: number;
    tool_call_count: number;
  };
}
