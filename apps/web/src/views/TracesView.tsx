import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { TraceDetailView } from "./TraceDetailView";

export function TracesView() {
  const [selected, setSelected] = useState<string | null>(null);
  const traces = useQuery({ queryKey: ["traces"], queryFn: () => api.listTraces() });

  if (traces.isPending) return <p>Loading traces...</p>;
  if (traces.isError) return <p className="error">Could not load traces: {traces.error.message}</p>;

  if (selected !== null) {
    return <TraceDetailView hash={selected} onBack={() => setSelected(null)} />;
  }
  if (traces.data.length === 0) return <p className="muted">No traces yet. Create a run first.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Trace</th>
          <th>Created</th>
          <th>Tokens in/out</th>
          <th>Cost</th>
          <th>Latency</th>
          <th>Tool calls</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {traces.data.map((trace) => (
          <tr key={trace.hash}>
            <td>
              <code>{trace.hash.slice(0, 12)}</code>
            </td>
            <td>{new Date(trace.created_at).toLocaleString()}</td>
            <td>
              {trace.total_input_tokens}/{trace.total_output_tokens}
            </td>
            <td>${trace.estimated_cost_usd}</td>
            <td>{trace.latency_ms} ms</td>
            <td>{trace.tool_call_count}</td>
            <td>
              <button onClick={() => setSelected(trace.hash)}>inspect</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
