#!/usr/bin/env bash
# cleanup-duplicates.sh
# Remove the top-level duplicate markdown files. Correct nested copies remain.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Top-level duplicates to remove. These all have correct copies elsewhere.
DUPLICATES=(
  "contributing.md"          # correct copy at docs/guides/contributing.md
  "database-schema.md"       # correct copy at docs/design/database-schema.md
  "kubernetes.md"            # correct copy at docs/deployment/kubernetes.md
  "session-design.md"        # correct copy at docs/design/session-design.md
  "system-design.md"         # correct copy at docs/design/system-design.md
  "bootstrap-github.sh"      # correct copy at scripts/bootstrap-github.sh
  "0001-deployment-topology.md"
  "0002-provider-adapter-pattern.md"
  "0003-content-addressed-trace-store.md"
  "0004-cost-model.md"
  "0005-database-architecture.md"
)

echo "==> Removing top-level duplicates"
for f in "${DUPLICATES[@]}"; do
  if [[ -f "$f" ]]; then
    git rm "$f"
    echo "   removed $f"
  else
    echo "   skipped $f (not present)"
  fi
done

echo "==> Committing cleanup"
git commit -m "chore: remove duplicate top-level files (correct copies live in docs/ and scripts/)"

echo "==> Pushing to current branch"
git push

echo
echo "Cleanup complete. Verify with: ls -la"
