# Agent Arena

A cost-aware, provider-agnostic evaluation platform for LLM agents, with
deterministic replay.

Agent Arena treats cost-per-correct-answer as a first-class leaderboard
metric, runs the same task across six LLM backends through a single adapter
interface, and captures every tool call to a content-addressed trace store
so old runs can be re-scored under new rubrics without re-spending tokens.

## Start here

- [Quickstart](guides/quickstart.md): clone to a scored leaderboard row in
  about five minutes.
- [System design](design/system-design.md): how the pieces fit together.
- [ADRs](adr/0001-deployment-topology.md): the decisions that shape what
  gets built and what does not.
- [Stability policy](STABILITY.md): what v1.0 guarantees.

## The three properties

1. **Cost is a first-class metric.** The leaderboard ranks agents by
   cost-per-correct-answer with bootstrap confidence intervals, computed
   from versioned per-token pricing data.
2. **Provider neutrality is enforced by the architecture.** One adapter
   interface covers OpenAI, Anthropic, Google, Bedrock, Ollama, and vLLM.
3. **Runs are reproducible without re-execution.** Every prompt, response,
   and tool call lands in a content-addressed trace store; new rubrics
   re-score old traces with no LLM calls.
