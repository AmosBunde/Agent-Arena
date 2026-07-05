# Per-issue Claude Code workflow

Two Claude Code sessions per issue: one as author, one as reviewer. The reviewer leaves structured feedback in a review file, the author re-implements, the reviewer signs off, then the PR opens. Bounded at two review rounds plus an optional third before re-scoping.

The aim is the rigour of human code review at solo-developer cost. The aim is not perfection; it is to catch obvious mistakes and architectural drift before they reach `dev`.

## Setup, once

```bash
cd ~/Agent-Arena
claude --version
cp /path/to/CLAUDE.md ./CLAUDE.md
mkdir -p .claude/prompts .claude/reviews
cp /path/to/author-prompt.md     .claude/prompts/author-prompt.md
cp /path/to/reviewer-prompt.md   .claude/prompts/reviewer-prompt.md
cp /path/to/reimplement-prompt.md .claude/prompts/reimplement-prompt.md
echo ".claude/reviews/" >> .gitignore   # keep reviews local by default
git add CLAUDE.md .claude/prompts/ .gitignore
git commit -m "docs: add Claude Code workflow prompts and CLAUDE.md"
git push
```

The review files are gitignored because they contain a lot of churn and are not part of the project's permanent record. If you want to keep them, remove the `.gitignore` line.

## The cycle, per issue

Nine steps. Not optional ceremony; each catches a real class of error.

### 1. Check out the issue branch

```bash
ISSUE=6   # set this to the issue number you are working on
git fetch origin
BRANCH=$(git branch -r | grep "origin/${ISSUE}-" | head -n1 | sed 's|.*origin/||')
git checkout -b "${BRANCH}" "origin/${BRANCH}"
```

### 2. Read the issue and the relevant ADRs

```bash
gh issue view "${ISSUE}" --repo AmosBunde/Agent-Arena
```

Open the ADRs the issue touches. The CLAUDE.md file at the repo root maps issue areas to required ADRs.

### 3. Author session

```bash
claude
```

Paste the contents of `.claude/prompts/author-prompt.md`, filling in `{ISSUE_NUMBER}`, `{ISSUE_TITLE}`, and `{ACCEPTANCE_CRITERIA}` from the issue body. Approve the plan before the implementation starts. Run tests locally as the author session progresses.

### 4. Commit, do not push

```bash
git status
git add -A
git commit -m "feat(area): short subject (#${ISSUE})"
```

The reviewer in step 5 reads local commits with `git log dev..HEAD`. Pushing here is fine if you want CI feedback, but the review happens against local state.

### 5. Reviewer session, round one

Exit Claude Code. Start a fresh session:

```bash
claude
```

Fresh context matters. Same-session "review your own work" is contaminated by the author's reasoning still in context.

Paste `.claude/prompts/reviewer-prompt.md`, filling in `{ISSUE_NUMBER}` and `{ROUND}` = 1. The reviewer writes findings to `.claude/reviews/${ISSUE}-round1.md`.

### 6. Read the review

This is the load-bearing human step. Read the file end to end. For each finding, mark one of:

- **MUST_FIX** (default for `severity: critical` or `severity: high`)
- **SHOULD_FIX** (default for `severity: medium`)
- **NIT** (default for `severity: low`, address only if cheap)
- **DISAGREE** with a one-line reason

Edit the review file in place to add these markers. The re-implementation session reads your annotations.

### 7. Re-implementation, round one

```bash
claude
```

Paste `.claude/prompts/reimplement-prompt.md`, filling in `{ISSUE_NUMBER}` and `{ROUND}` = 1. It reads the annotated review file and addresses every `MUST_FIX` and every `SHOULD_FIX` not marked `DISAGREE`. Each change goes in a separate commit with a message explaining what it fixes.

```bash
git add -A
git commit -m "fix(area): address round 1 review (#${ISSUE})"
```

Run tests again.

### 8. Reviewer session, round two

Same reviewer prompt, `{ROUND}` = 2, output to `.claude/reviews/${ISSUE}-round2.md`. The prompt tells the reviewer this is round two and that the bar for `REQUEST_CHANGES` is higher: only previously-unaddressed findings or new issues introduced by the re-implementation.

If round-two verdict is APPROVE, proceed to step 9.
If REQUEST_CHANGES, repeat steps 6 and 7 for round 3, output `${ISSUE}-round3.md`.
If round three is also not APPROVE, stop and re-scope. Do not let any single issue exceed three rounds.

### 9. Push and open the PR

```bash
git push origin "${BRANCH}"

gh pr create \
  --base dev \
  --head "${BRANCH}" \
  --title "feat(area): short subject" \
  --body "Closes #${ISSUE}.

Review rounds completed: 1, 2$([ -f .claude/reviews/${ISSUE}-round3.md ] && echo ', 3')." \
  --draft

# When CI is green and you are satisfied:
gh pr ready
gh pr merge --squash
git checkout dev && git pull
```

## Execution order for M1

Dependency-aware. Each issue's number depends on the order issues were created by the bootstrap script; check `gh issue list --milestone "M1: Foundation and core loop"` for the actual numbers.

1. Postgres schema and Alembic migrations
2. Set up CI
3. Provider adapter protocol and registry
4. Cost model and pricing data
5. OpenAI adapter
6. Anthropic adapter
7. Ollama adapter
8. Docker Compose deployment
9. Celery runner and agent loop
10. FastAPI service with M1 endpoints
11. Leaderboard view and CPCA
12. Minimal React UI
13. Example tasks and rubrics
14. Quick start guide

## When to walk away from the review

If you notice yourself approving every finding without thinking, stop. The review is no longer doing its job. The whole point is that a human gates the changes. If you are not gating, you are not getting the value, you are just spending tokens.
