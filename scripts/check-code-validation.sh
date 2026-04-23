#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

echo "code-validation: checking shell script syntax"
while IFS= read -r script; do
  bash -n "$script"
done < <(find scripts -maxdepth 1 -type f -name "*.sh" | sort)

if command -v shellcheck >/dev/null 2>&1; then
  echo "code-validation: running shellcheck"
  shellcheck scripts/*.sh
else
  echo "code-validation: shellcheck not installed; skipped optional lint"
fi

echo "code-validation: checking json artifacts"
python3 - <<'PY'
import json
from pathlib import Path

paths = [
    Path(".ai/PLANS/progress.json"),
    Path(".ai/EVALS/metrics.json"),
    Path(".ai/ADAPTERS/claude/settings.json"),
    Path(".ai/ADAPTERS/codex/hooks.json"),
    Path(".claude/settings.json"),
    Path(".codex/hooks.json"),
]

for path in paths:
    with path.open("r", encoding="utf-8") as fh:
        json.load(fh)
PY

echo "code-validation: checking toml artifacts"
python3 - <<'PY'
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        print("code-validation: no toml parser available; skipped toml syntax check")
        raise SystemExit(0)

for path in [Path(".ai/ADAPTERS/codex/config.toml"), Path(".codex/config.toml")]:
    with path.open("rb") as fh:
        tomllib.load(fh)
PY

python_files=()
node_files=()
while IFS= read -r file; do
  [[ -f "$file" ]] || continue
  case "$file" in
    .git/*|node_modules/*|vendor/*|dist/*|build/*|.next/*|coverage/*)
      continue
      ;;
    *.py)
      python_files+=("$file")
      ;;
    *.js|*.mjs|*.cjs)
      node_files+=("$file")
      ;;
  esac
done < <(
  {
    git diff --name-only --diff-filter=ACMRTUXB HEAD -- 2>/dev/null || true
    git ls-files --others --exclude-standard -- 2>/dev/null || true
  } | sort -u
)

if [[ "${#python_files[@]}" -gt 0 ]]; then
  echo "code-validation: compiling changed python files"
  python3 -m py_compile "${python_files[@]}"
fi

if [[ "${#node_files[@]}" -gt 0 ]]; then
  if command -v node >/dev/null 2>&1; then
    echo "code-validation: checking changed javascript files"
    for file in "${node_files[@]}"; do
      node --check "$file"
    done
  else
    echo "code-validation: node not installed; skipped javascript syntax check"
  fi
fi

echo "code-validation: checking conflict markers"
if git grep -n -E '^(<<<<<<<|=======|>>>>>>>)' -- . ':!*.jsonl' ':!*.patch' >/tmp/harness-conflict-markers.$$; then
  cat /tmp/harness-conflict-markers.$$
  rm -f /tmp/harness-conflict-markers.$$
  exit 1
fi
rm -f /tmp/harness-conflict-markers.$$

echo "code-validation: ok"
