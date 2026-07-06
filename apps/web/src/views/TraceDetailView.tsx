import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import type { TraceMessage, TraceStep } from "../types";

export function TraceDetailView({ hash, onBack }: { hash: string; onBack: () => void }) {
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["trace", hash], queryFn: () => api.getTrace(hash) });
  const body = useQuery({ queryKey: ["trace-body", hash], queryFn: () => api.getTraceBody(hash) });
  const rubrics = useQuery({ queryKey: ["rubrics"], queryFn: api.listRubrics });
  const [rubricId, setRubricId] = useState("");

  const rescore = useMutation({
    mutationFn: () => api.rescoreTrace(hash, rubricId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["trace", hash] }),
  });

  if (detail.isPending || body.isPending) return <p>Loading trace...</p>;
  if (detail.isError)
    return <p className="error">Could not load the trace: {detail.error.message}</p>;

  return (
    <div>
      <button onClick={onBack}>back to traces</button>
      <h2>
        Trace <code>{hash.slice(0, 12)}</code>
      </h2>

      <table>
        <tbody>
          <tr>
            <th>Run</th>
            <td>{detail.data.run_id}</td>
            <th>Created</th>
            <td>{new Date(detail.data.created_at).toLocaleString()}</td>
          </tr>
          <tr>
            <th>Tokens in / out / cached</th>
            <td>
              {detail.data.total_input_tokens} / {detail.data.total_output_tokens} /{" "}
              {detail.data.total_cached_tokens}
            </td>
            <th>Estimated cost</th>
            <td>${detail.data.estimated_cost_usd}</td>
          </tr>
          <tr>
            <th>Latency</th>
            <td>{detail.data.latency_ms} ms</td>
            <th>Tool calls</th>
            <td>{detail.data.tool_call_count}</td>
          </tr>
        </tbody>
      </table>

      <h3>Scores</h3>
      {detail.data.scores.length === 0 ? (
        <p className="muted">Not scored yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Rubric hash</th>
              <th>Score</th>
              <th>Correct</th>
              <th>Judge model</th>
              <th>Scored at</th>
            </tr>
          </thead>
          <tbody>
            {detail.data.scores.map((score) => (
              <tr key={score.rubric_hash}>
                <td>
                  <code>{score.rubric_hash.slice(0, 12)}</code>
                </td>
                <td>{score.score}</td>
                <td>{score.is_correct ? "yes" : "no"}</td>
                <td>{score.judge_model ?? "-"}</td>
                <td>{new Date(score.scored_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Re-score under another rubric</h3>
      <p className="muted">Applies the rubric to the stored trace. No LLM calls, no new spend.</p>
      <label>
        Rubric
        <select value={rubricId} onChange={(event) => setRubricId(event.target.value)}>
          <option value="">choose</option>
          {(rubrics.data ?? []).map((rubric) => (
            <option key={rubric.id} value={rubric.id}>
              {rubric.slug}@{rubric.version}
            </option>
          ))}
        </select>
      </label>
      <button disabled={rubricId === "" || rescore.isPending} onClick={() => rescore.mutate()}>
        {rescore.isPending ? "Scoring..." : "Re-score"}
      </button>
      {rescore.isError && <p className="error">Re-scoring failed: {rescore.error.message}</p>}

      <h3>Timeline</h3>
      {body.isError ? (
        <p className="error">Trace body unavailable: {body.error.message}</p>
      ) : (
        <div>
          {body.data.steps.map((step) => (
            <StepCard key={step.index} step={step} />
          ))}
          <p>
            <strong>Final answer:</strong> {body.data.final_answer ?? "none"}
            {body.data.error && <span className="error"> (error: {body.data.error})</span>}
          </p>
        </div>
      )}
    </div>
  );
}

function StepCard({ step }: { step: TraceStep }) {
  return (
    <fieldset>
      <legend>
        Turn {step.index + 1}: {step.response.usage.prompt_tokens} in /{" "}
        {step.response.usage.completion_tokens} out tokens, {step.response.latency_ms} ms
      </legend>
      {step.request_messages.map((message, index) => (
        <MessageLine key={index} message={message} />
      ))}
      <p>
        <strong>assistant:</strong> {step.response.content ?? ""}
        {step.response.tool_calls.map((call) => (
          <span key={call.id} className="muted">
            {" "}
            [calls {call.name}({JSON.stringify(call.arguments)})]
          </span>
        ))}
      </p>
      {step.tool_results.map((result) => (
        <p key={result.tool_call_id} className="muted">
          <strong>{result.name} result:</strong> {result.output}
        </p>
      ))}
    </fieldset>
  );
}

function MessageLine({ message }: { message: TraceMessage }) {
  return (
    <p className="muted">
      <strong>{message.role}:</strong> {message.content ?? ""}
      {message.tool_calls.length > 0 && ` [${message.tool_calls.length} tool calls]`}
    </p>
  );
}
