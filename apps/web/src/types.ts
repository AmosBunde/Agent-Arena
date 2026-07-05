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
}
