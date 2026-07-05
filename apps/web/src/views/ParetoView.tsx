import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

// Dominated points are dimmed, not hidden (issue #24): the tradeoff is only
// meaningful when the losing configurations stay visible.
export function ParetoView() {
  const rows = useQuery({ queryKey: ["pareto"], queryFn: api.paretoFront });

  if (rows.isPending) return <p>Loading Pareto view...</p>;
  if (rows.isError)
    return <p className="error">Could not load the Pareto view: {rows.error.message}</p>;
  if (rows.data.length === 0) return <p className="muted">No scored runs yet.</p>;

  return (
    <div>
      <p className="muted">
        Cost is mean dollars per task; accuracy is the pass rate. Rows on the (cost, accuracy)
        Pareto front are full strength; dominated rows are dimmed.
      </p>
      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>Model</th>
            <th>Mean cost per task</th>
            <th>Accuracy</th>
            <th>CPCA</th>
            <th>Front</th>
          </tr>
        </thead>
        <tbody>
          {rows.data.map((row) => (
            <tr
              key={`${row.agent_id}-${row.task_id}-${row.provider}-${row.model}-${row.rubric_hash}`}
              className={row.on_front ? undefined : "dominated"}
            >
              <td>{row.provider}</td>
              <td>{row.model}</td>
              <td>${row.mean_cost_usd}</td>
              <td>{(Number(row.accuracy) * 100).toFixed(1)}%</td>
              <td>{row.cost_per_correct_usd === null ? "-" : `$${row.cost_per_correct_usd}`}</td>
              <td>{row.on_front ? "yes" : "dominated"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
