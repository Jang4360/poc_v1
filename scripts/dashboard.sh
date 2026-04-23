#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT_DIR/scripts/update-progress.sh" >/dev/null
"$ROOT_DIR/scripts/update-metrics.sh" >/dev/null

python3 - <<'PY' "$ROOT_DIR"
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

root = Path(sys.argv[1])
progress = json.loads((root / ".ai" / "PLANS" / "progress.json").read_text(encoding="utf-8"))
metrics = json.loads((root / ".ai" / "EVALS" / "metrics.json").read_text(encoding="utf-8"))
promotion_path = root / ".ai" / "EVALS" / "promotion-log.jsonl"
retry_path = root / ".ai" / "EVALS" / "retry-log.jsonl"

promotion_count = 0
if promotion_path.exists():
    for line in promotion_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("destination") == "none":
                continue
            promotion_count += 1

adr_count = 0
for p in (root / ".ai" / "DECISIONS").glob("*.md"):
    if p.name != "ADR-template.md":
        adr_count += 1

# Retry cluster analysis: count signatures in last 24h
retry_clusters = Counter()
circuit_breaker_threshold = 3
window_start = datetime.now(timezone.utc) - timedelta(hours=24)
if retry_path.exists():
    for line in retry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            sig = item.get("signature", "")
            ts = item.get("timestamp", "")
            note = item.get("note", "")
            if not sig or sig == "placeholder" or note:
                continue
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt >= window_start:
                retry_clusters[sig] += 1
        except Exception:
            continue

hot_clusters = {sig: cnt for sig, cnt in retry_clusters.items() if cnt >= circuit_breaker_threshold}

summary = progress.get("summary", {})
items = progress.get("items", [])
blocked = [item for item in items if item.get("status") == "blocked"]
in_progress = [item for item in items if item.get("status") == "in_progress"]

print("Dashboard")
print("")
print("Progress")
print(f"- Sprint: {progress.get('sprint_name', 'unknown')}")
print(f"- Planned: {summary.get('planned', 0)}")
print(f"- Completed: {summary.get('completed', 0)}")
print(f"- In progress: {summary.get('in_progress', 0)}")
print(f"- Blocked: {summary.get('blocked', 0)}")
print(f"- Progress %: {summary.get('progress_percentage', 0)}")
print(f"- Quality-adjusted progress: {summary.get('quality_adjusted_progress', 0)}")
print(f"- Confidence score: {summary.get('confidence_score', 'n/a')}")

print("")
print("Quality")
for key in [
    "first_pass_success_rate",
    "retry_count",
    "test_pass_rate",
    "missed_acceptance_criteria",
    "risk_carry_over_count",
    "repeated_failure_rate",
    "skill_reuse_rate",
    "unresolved_blocker_count",
    "release_readiness_confidence",
    "harness_health_score",
]:
    print(f"- {key}: {metrics.get(key)}")

print("")
print("Harness")
print(f"- Promotion events logged: {promotion_count}")
print(f"- ADR count: {adr_count}")
print(f"- Blocked items: {len(blocked)}")
print(f"- In-progress items: {len(in_progress)}")
print(f"- Retry clusters (>=3 in 24h): {len(hot_clusters)}")

if hot_clusters:
    print("")
    print("Circuit breaker — repeated failure clusters (run 'learn' skill)")
    for sig, cnt in sorted(hot_clusters.items(), key=lambda x: -x[1]):
        print(f"  [{cnt}x] {sig}")

if blocked:
    print("")
    print("Blocked items")
    for item in blocked:
        print(f"- {item.get('id')}: {item.get('title')}")

if in_progress:
    print("")
    print("In-progress items")
    for item in in_progress:
        print(f"- {item.get('id')}: {item.get('title')}")
PY
