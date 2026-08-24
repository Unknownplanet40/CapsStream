#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  CapsStream release helper (developer tool)
#  Usage:
#    ./scripts/release.sh 2.0.1        # bumps VERSION, tags v2.0.1, pushes
# ─────────────────────────────────────────────────────────────
set -euo pipefail

VER="${1:-}"
if [ -z "$VER" ]; then
  echo "Usage: ./scripts/release.sh X.Y.Z[.W]"
  exit 1
fi

# Basic format check
if ! echo "$VER" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$'; then
  echo "ERROR: '$VER' is not a valid X.Y.Z[.W] version"
  exit 1
fi

# Must run from the repo root
cd "$(dirname "$0")/.."

echo "$VER" > VERSION

git add VERSION
git commit -m "chore: release v$VER" || true
git tag "v$VER"
git push origin main
git push origin "v$VER"

echo ""
echo "Tag v$VER pushed. GitHub Actions will build the release."
echo "Watch: https://github.com/$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s/\.git$##')/actions"
