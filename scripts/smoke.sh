#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT_DIR/scripts/verify.sh"

if [[ -z "${HARNESS_SMOKE_COMMAND:-}" ]]; then
  echo "smoke: no project-specific smoke command configured"
  echo 'TODO(project): set HARNESS_SMOKE_COMMAND to the real smoke command or replace the placeholder in scripts/smoke.sh'
  exit 0
fi

echo "smoke: running configured command"
bash -lc "$HARNESS_SMOKE_COMMAND"
