import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import type { ProviderModel, RunGroup } from "../types";

const KNOWN_PROVIDERS = ["openai", "anthropic", "google", "ollama"];

export function NewRunView() {
  const queryClient = useQueryClient();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.listTasks });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.listAgents });
  const rubrics = useQuery({ queryKey: ["rubrics"], queryFn: api.listRubrics });

  const [taskId, setTaskId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [rubricId, setRubricId] = useState("");
  const [providers, setProviders] = useState<ProviderModel[]>([{ provider: "openai", model: "" }]);
  const [group, setGroup] = useState<RunGroup | null>(null);

  const create = useMutation({
    mutationFn: api.createRuns,
    onSuccess: (created) => {
      setGroup(created);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  const groupRuns = useQuery({
    queryKey: ["runs", group?.run_group_id],
    queryFn: () => api.listRuns(group?.run_group_id),
    enabled: group !== null,
    refetchInterval: 3000,
  });

  if (tasks.isPending || agents.isPending || rubrics.isPending) return <p>Loading catalog...</p>;
  if (tasks.isError || agents.isError || rubrics.isError)
    return <p className="error">Could not load the catalog.</p>;

  const ready =
    taskId !== "" &&
    agentId !== "" &&
    rubricId !== "" &&
    providers.length > 0 &&
    providers.every((entry) => entry.provider !== "" && entry.model !== "");

  return (
    <div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate({ task_id: taskId, agent_id: agentId, rubric_id: rubricId, providers });
        }}
      >
        <fieldset>
          <legend>What to run</legend>
          <label>
            Task
            <select value={taskId} onChange={(event) => setTaskId(event.target.value)} required>
              <option value="">choose</option>
              {tasks.data.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.slug}@{task.version}
                </option>
              ))}
            </select>
          </label>
          <label>
            Agent
            <select value={agentId} onChange={(event) => setAgentId(event.target.value)} required>
              <option value="">choose</option>
              {agents.data.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.slug}@{agent.version}
                </option>
              ))}
            </select>
          </label>
          <label>
            Rubric
            <select value={rubricId} onChange={(event) => setRubricId(event.target.value)} required>
              <option value="">choose</option>
              {rubrics.data.map((rubric) => (
                <option key={rubric.id} value={rubric.id}>
                  {rubric.slug}@{rubric.version}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        <fieldset>
          <legend>Providers</legend>
          {providers.map((entry, index) => (
            <label key={index}>
              <select
                value={entry.provider}
                onChange={(event) =>
                  setProviders(
                    providers.map((item, i) =>
                      i === index ? { ...item, provider: event.target.value } : item,
                    ),
                  )
                }
              >
                {KNOWN_PROVIDERS.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <input
                placeholder="model identifier"
                value={entry.model}
                onChange={(event) =>
                  setProviders(
                    providers.map((item, i) =>
                      i === index ? { ...item, model: event.target.value } : item,
                    ),
                  )
                }
                required
              />
              {providers.length > 1 && (
                <button
                  type="button"
                  onClick={() => setProviders(providers.filter((_, i) => i !== index))}
                >
                  remove
                </button>
              )}
            </label>
          ))}
          <button
            type="button"
            onClick={() => setProviders([...providers, { provider: "openai", model: "" }])}
          >
            add provider
          </button>
        </fieldset>
        <button type="submit" disabled={!ready || create.isPending}>
          {create.isPending ? "Creating..." : "Create runs"}
        </button>
        {create.isError && <p className="error">Run creation failed: {create.error.message}</p>}
      </form>

      {group && (
        <section>
          <h2>Run group {group.run_group_id}</h2>
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Provider</th>
                <th>Model</th>
                <th>Status</th>
                <th>Failure reason</th>
              </tr>
            </thead>
            <tbody>
              {(groupRuns.data ?? group.runs).map((run) => (
                <tr key={run.id}>
                  <td>{run.id.slice(0, 8)}</td>
                  <td>{run.provider}</td>
                  <td>{run.model}</td>
                  <td>{run.status}</td>
                  <td>{run.failure_reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Statuses refresh every three seconds.</p>
        </section>
      )}
    </div>
  );
}
