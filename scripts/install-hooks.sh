#!/usr/bin/env bash
# Install the repo's git hooks into .git/hooks/.
# Run once per clone:  bash scripts/install-hooks.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/scripts/git-hooks"
DEST="$ROOT/.git/hooks"

mkdir -p "$DEST"
for hook in "$SRC"/*; do
  name="$(basename "$hook")"
  cp "$hook" "$DEST/$name"
  chmod +x "$DEST/$name"
  echo "installed: .git/hooks/$name"
done
echo "Done. Commit messages now auto-bump server/version.py (see scripts/bump_version.py)."
