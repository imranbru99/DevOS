#!/usr/bin/env bash
# Create/update the fixed GitHub Release used for anonymous install counting.
# Safe to re-run. Requires: gh auth login
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${DEVOS_GITHUB_REPO:-imranbru99/DevOS}"
TAG="install-ping"
ASSET="$ROOT/stats/devos-install.ping"

test -f "$ASSET"
gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 || \
  gh release create "$TAG" --repo "$REPO" \
    --title "DevOS install counter" \
    --notes "Tiny asset used once per install so GitHub can count installs. Not a product release."

# Replace asset if present (gh upload --clobber).
gh release upload "$TAG" "$ASSET" --repo "$REPO" --clobber
echo "Published $ASSET on $REPO @$TAG"
echo "URL: https://github.com/${REPO}/releases/download/${TAG}/devos-install.ping"
