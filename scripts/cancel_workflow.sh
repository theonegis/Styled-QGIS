#!/usr/bin/env bash

set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"

echo "::error::A critical job failed; cancelling the complete workflow run"
gh api \
  --method POST \
  "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/cancel"
