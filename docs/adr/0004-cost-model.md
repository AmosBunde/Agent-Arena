# ADR-0004: Cost model and primary metric

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Core maintainers

## Context

Cost-awareness is the headline differentiator of Agent Arena. Getting this wrong, or treating cost as a secondary metric bolted onto an accuracy-centric design, would undermine the entire positioning.

The questions to answer are:

1. What is the primary metric on the leaderboard?
2. How is cost computed, given that vendor pricing changes?
3. How are non-dollar costs (latency, energy, local compute) represented?
4. How are costs presented when the model is run locally and the marginal cost is effectively zero?

Vendor pricing changes frequently. OpenAI, Anthropic, and Google have each repriced multiple times in the last twelve months. If pricing is hardcoded, the leaderboard is wrong by construction. If pricing is computed at query time, historical leaderboards become unstable. Neither is acceptable.

## Decision

**Primary leaderboard metric is cost-per-correct-answer (CPCA).** Defined as total dollars spent across all attempts at a task divided by the number of correctly answered attempts. This is the metric that surfaces the engineering tradeoff Agent Arena exists to expose: a model that is 5 percent more accurate but 10x more expensive is not necessarily a better choice for the task.

Secondary metrics, all surfaced on the leaderboard:

- **Accuracy.** Standard pass rate.
- **Dollars-per-task.** Mean cost regardless of correctness.
- **p50 and p95 latency.** From adapter-level wall clock measurement.
- **Tokens-per-task.** Mean total tokens.
- **Tool-call count per task.** A proxy for agent verbosity.

**Pricing is versioned data.** `packages/cost-models/` contains one YAML file per provider, with a `valid_from` date for each price line. A cost computation always uses the price that was valid at the time of the trace's `created_at`. This means historical leaderboards are stable; only the prices applied to runs at the time those runs happened are used.

```yaml
# packages/cost-models/anthropic.yaml
provider: anthropic
prices:
  - model: claude-opus-4-7
    valid_from: 2026-02-15
    input_per_million_tokens: 15.00
    output_per_million_tokens: 75.00
    cached_input_per_million_tokens: 1.50
```

**Local models have a configurable cost-per-hour.** Ollama and vLLM adapters compute cost as `(latency_seconds / 3600) * hourly_rate`, with the hourly rate set per deployment in environment configuration. Default is zero, with a documented warning that this makes local models look free relative to commercial APIs, which they are not.

**Non-dollar costs are surfaced but not aggregated into CPCA.** Energy estimates are out of scope for v0.1; they may be added in M4 if a defensible model can be defined.

## Consequences

### Positive

The leaderboard says something the rest of the ecosystem does not. Ranking by CPCA surfaces engineering decisions that accuracy-only rankings obscure: that GPT-4o-mini may be the right choice for 90 percent of an agent's calls, that Claude Opus is overkill for routing tasks, that local models are competitive on cost for high-volume workloads.

Historical leaderboards are stable. A run from March 2026 will always show the same cost regardless of when the leaderboard is queried, because the price applied was the one valid in March 2026.

The pricing data is auditable. Anyone can read `packages/cost-models/` and see exactly what numbers produced any leaderboard cell. Disputes about pricing become PRs against the data file.

### Negative

Maintaining accurate pricing is ongoing work. When a provider reprices, someone must update the YAML. The mitigation is a documented process and an issue template for pricing updates, plus a quarterly audit issue.

CPCA is ill-defined when zero answers are correct. The handling is explicit: tasks with zero correct answers report `CPCA = ∞` and are sorted last; the UI shows them as "no correct answers" rather than a number.

CPCA can be gamed by skipping hard tasks. A model that refuses to attempt difficult tasks looks cheap because its denominator is small. The mitigation is that the leaderboard always requires a minimum attempt rate; runs below the threshold are not ranked.

### Neutral

Local model cost is a known soft spot. There is no principled way to compare a 70B model running on a 4090 to GPT-4o without making assumptions about hardware amortisation. The chosen approach (configurable hourly rate, defaulting to zero, with a warning) is the least-bad option.

## Alternatives considered

**Accuracy as primary, cost as a column.** Rejected. This is what the rest of the ecosystem does. Doing it again would forfeit the positioning.

**Pareto front instead of a single primary metric.** Considered. Will be added as a leaderboard view in M3, but a sortable table needs a default sort key, and CPCA is the right one.

**Real-time pricing from vendor APIs.** Rejected. Most providers do not expose pricing programmatically. The few that do, do so for predictable cases only. The maintenance burden of a pricing scraper exceeds the burden of manual YAML updates.

## References

- HELM benchmark uses accuracy primarily, cost not surfaced.
- LMSys arena uses Elo rating, cost not surfaced.
- artificialanalysis.ai surfaces cost prominently but is a third-party aggregator, not a benchmark.

## Revision history

- 2026-05-11: Initial decision recorded.
