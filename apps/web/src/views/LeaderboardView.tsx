import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

// ADR-0004: a group with zero correct answers has no defined CPCA; the UI
// shows "no correct answers" rather than a number.
function formatCpca(value: string | null): string {
  return value === null ? "no correct answers" : `$${value}`;
}

export function LeaderboardView() {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const leaderboard = useQuery({
    queryKey: ["leaderboard"],
    queryFn: () => api.leaderboard(false),
  });

  async function refreshNow() {
    setRefreshing(true);
    try {
      const rows = await api.leaderboard(true);
      queryClient.setQueryData(["leaderboard"], rows);
    } finally {
      setRefreshing(false);
    }
  }

  if (leaderboard.isPending) return <p>Loading leaderboard...</p>;
  if (leaderboard.isError)
    return <p className="error">Could not load the leaderboard: {leaderboard.error.message}</p>;

  return (
    <div>
      <button onClick={() => void refreshNow()} disabled={refreshing}>
        {refreshing ? "Refreshing..." : "Refresh now"}
      </button>
      {leaderboard.data.length === 0 ? (
        <p className="muted">No scored runs yet. Create a run and check back.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Model</th>
              <th>CPCA</th>
              <th>Accuracy</th>
              <th>Mean score</th>
              <th>Total cost</th>
              <th>p50 latency</th>
              <th>p95 latency</th>
            </tr>
          </thead>
          <tbody>
            {leaderboard.data.map((row) => (
              <tr
                key={`${row.agent_id}-${row.task_id}-${row.provider}-${row.model}-${row.rubric_hash}`}
              >
                <td>{row.provider}</td>
                <td>{row.model}</td>
                <td>{formatCpca(row.cost_per_correct_usd)}</td>
                <td>
                  {row.correct_count}/{row.total_count}
                </td>
                <td>{row.mean_score}</td>
                <td>${row.total_cost_usd}</td>
                <td>{row.p50_latency_ms ?? "-"} ms</td>
                <td>{row.p95_latency_ms ?? "-"} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
