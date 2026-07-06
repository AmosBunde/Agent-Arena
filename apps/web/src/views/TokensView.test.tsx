import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ApiToken, CreatedApiToken } from "../types";
import { TokensView } from "./TokensView";

const EXISTING: ApiToken = {
  id: "t1",
  name: "ci-bot",
  prefix: "abcd1234",
  role: "runner",
  created_by: "local",
  created_at: "2026-07-06T00:00:00Z",
  expires_at: null,
  revoked_at: null,
};

const CREATED: CreatedApiToken = {
  ...EXISTING,
  id: "t2",
  name: "new-token",
  prefix: "eeff0011",
  role: "viewer",
  token: "arena_eeff0011_secret-value",
};

vi.mock("../api", () => ({
  api: { listTokens: vi.fn(), createToken: vi.fn(), revokeToken: vi.fn() },
}));

const { api } = await import("../api");
vi.mocked(api.listTokens).mockResolvedValue([EXISTING]);
vi.mocked(api.createToken).mockResolvedValue(CREATED);

describe("TokensView", () => {
  it("lists tokens without secrets and shows a created token once", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TokensView />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("ci-bot")).toBeInTheDocument();
    expect(screen.getByText("abcd1234")).toBeInTheDocument();
    expect(screen.queryByText(/arena_/)).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Name"), "new-token");
    await userEvent.click(screen.getByText("Create token"));
    expect(await screen.findByText("arena_eeff0011_secret-value")).toBeInTheDocument();
    expect(screen.getByText(/shown once/)).toBeInTheDocument();
  });
});
