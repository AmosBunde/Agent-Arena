import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import type { CreatedApiToken } from "../types";

// Admin-only token management (issue #30). The plaintext token is shown
// exactly once, immediately after creation; the list never contains it.
export function TokensView() {
  const queryClient = useQueryClient();
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: api.listTokens });
  const [name, setName] = useState("");
  const [role, setRole] = useState("viewer");
  const [justCreated, setJustCreated] = useState<CreatedApiToken | null>(null);

  const create = useMutation({
    mutationFn: () => api.createToken(name, role),
    onSuccess: (created) => {
      setJustCreated(created);
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["tokens"] });
    },
  });
  const revoke = useMutation({
    mutationFn: api.revokeToken,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["tokens"] }),
  });

  if (tokens.isPending) return <p>Loading tokens...</p>;
  if (tokens.isError)
    return (
      <p className="error">Could not load tokens (admin role required): {tokens.error.message}</p>
    );

  return (
    <div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <fieldset>
          <legend>Create a token</legend>
          <label>
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label>
            Role
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="viewer">viewer</option>
              <option value="runner">runner</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <button type="submit" disabled={name === "" || create.isPending}>
            {create.isPending ? "Creating..." : "Create token"}
          </button>
          {create.isError && <p className="error">Creation failed: {create.error.message}</p>}
        </fieldset>
      </form>

      {justCreated && (
        <fieldset>
          <legend>Token created</legend>
          <p>
            Copy it now; it is shown once and stored only as a hash:{" "}
            <code>{justCreated.token}</code>
          </p>
        </fieldset>
      )}

      {tokens.data.length === 0 ? (
        <p className="muted">No tokens yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Prefix</th>
              <th>Role</th>
              <th>Created by</th>
              <th>Expires</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tokens.data.map((token) => (
              <tr key={token.id}>
                <td>{token.name}</td>
                <td>
                  <code>{token.prefix}</code>
                </td>
                <td>{token.role}</td>
                <td>{token.created_by}</td>
                <td>{token.expires_at ? new Date(token.expires_at).toLocaleString() : "never"}</td>
                <td>{token.revoked_at ? "revoked" : "active"}</td>
                <td>
                  {!token.revoked_at && (
                    <button onClick={() => revoke.mutate(token.id)} disabled={revoke.isPending}>
                      revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
