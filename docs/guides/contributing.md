# Contributing to Agent Arena

Read this before opening a PR. The goal is to keep the project's architecture coherent over time, not to gatekeep.

## Branching model

Two long-lived branches:

- `main` is the release branch. It receives merges only from `dev` as part of a release cut. Direct pushes are forbidden.
- `dev` is the integration branch. All feature work targets `dev` via PR.

Feature work happens on issue-numbered branches off `dev`. Naming: `{issue-number}-{short-slug}`, for example `42-bedrock-adapter`. The bootstrap script creates one such branch per issue at repo setup. New issues opened after bootstrap should follow the same pattern.

A typical workflow:

```bash
git fetch origin
git checkout dev
git pull
git checkout -b 87-foo-feature
# ... work, commit, push
gh pr create --base dev --title "feat(adapters): foo feature" --body "Closes #87"
```

## Commit messages

Conventional Commits. The prefix matters for changelog generation and for at-a-glance scanning of history.

Allowed prefixes: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`. Scope in parentheses where useful (`feat(adapters): ...`). Breaking changes carry a `!` (`feat(adapters)!: rename Capability enum`).

Commit early, commit often, within a feature branch. Squash on merge to `dev` is the default; long-lived branches with informative history can opt out via PR description.

## Code style

Python: `ruff` for lint, `ruff format` for formatting, `mypy --strict` for the public packages (`packages/`) and `mypy` (non-strict) for the apps. Tests with `pytest`.

TypeScript: `eslint` with the project config, `prettier` for formatting, `tsc --noEmit` for type checks. Tests with `vitest` for unit, Playwright for end-to-end.

Both languages: no trailing whitespace, LF line endings, files end with a newline.

## ADR amendment process

Architecture Decision Records are not silently overridden. If your PR changes a decision documented in an ADR, the PR must include an amendment:

1. Open a discussion or issue describing the proposed amendment.
2. Add a new section to the ADR titled `## Amendment: <date>` with the change, the rationale, and the consequences.
3. Update the `Status` field at the top of the ADR if the decision is reversed.
4. Reference the discussion in the PR.

This sounds heavy. It is. It is also the only thing that prevents architecture drift in projects that survive past their first year. ADR-level changes are rare; almost all PRs do not touch ADRs.

## PR checklist

The template at [.github/pull_request_template.md](../../.github/pull_request_template.md) pre-fills every new PR with this checklist, so you tick the boxes in the PR body itself. For reference:

- The PR targets `dev`, not `main`.
- The PR is linked to an issue via `Closes #N`.
- New behaviour is covered by tests at the appropriate level.
- Documentation is updated if user-facing behaviour changes.
- ADRs are amended if architectural decisions are touched.
- The commit history is clean enough that the reviewer can read it linearly.

Continuous integration runs on every PR into `dev` and `main`; the required jobs are `lint`, `type-check`, `test`, `typescript`, and `smoke` (see [.github/workflows/ci.yml](../../.github/workflows/ci.yml)). The smoke job deploys the full Compose stack and probes the health endpoints, so a PR that breaks the deployment fails CI even when unit tests pass.

## Reviewing

One approval is required to merge into `dev`, two for `main`. Reviewers should focus on:

- Architectural fit (does this respect the ADRs?).
- Correctness of the agent and adapter semantics.
- Test coverage at the right level (unit for pure logic, integration for adapter contracts, end-to-end for user flows).
- Whether the change is the smallest one that solves the problem.

Reviewers should not focus on personal style preferences; the linters handle style.

## Release cadence

Minor releases monthly, patch releases as needed. Major releases at milestone boundaries (M1, M2, ...) with a CHANGELOG entry summarising the milestone. The v1.0 release at M5 is the first version with the stability guarantee documented in `docs/STABILITY.md`.

## Reporting security issues

Do not open public issues for security reports. Email the maintainer addresses listed in `SECURITY.md`. We will acknowledge within 72 hours and coordinate a fix and disclosure.
