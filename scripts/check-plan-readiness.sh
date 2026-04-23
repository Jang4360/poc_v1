#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$ROOT_DIR/.ai/PLANS/current-sprint.md}"

if [[ ! -f "$TARGET" ]]; then
  echo "plan-readiness: missing target file: $TARGET" >&2
  exit 1
fi

required_sections=(
  "## Problem List"
  "## Architecture And Data Flow"
  "## Execution Units"
  "## Test And Validation Matrix"
  "## Risk Register"
  "## Review Handoff"
  "## QA Handoff"
  "## Open Questions"
)

missing=0
for section in "${required_sections[@]}"; do
  if ! grep -q "^${section}$" "$TARGET"; then
    echo "plan-readiness: missing section '$section' in $TARGET" >&2
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  exit 2
fi

echo "plan-readiness: ok"
