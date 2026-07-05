import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export function TasksView() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.listTasks });

  if (tasks.isPending) return <p>Loading tasks...</p>;
  if (tasks.isError) return <p className="error">Could not load tasks: {tasks.error.message}</p>;
  if (tasks.data.length === 0) return <p className="muted">No tasks yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Slug</th>
          <th>Version</th>
          <th>Domain</th>
          <th>Required capabilities</th>
          <th>Contamination</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {tasks.data.map((task) => (
          <tr key={task.id}>
            <td>{task.slug}</td>
            <td>{task.version}</td>
            <td>{task.domain}</td>
            <td>{task.capabilities_required.join(", ") || "none"}</td>
            <td>{task.contamination?.status ?? "unchecked"}</td>
            <td>{new Date(task.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
