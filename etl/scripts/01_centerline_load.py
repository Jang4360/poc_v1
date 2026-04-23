#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import centerline_loader


def print_report(name: str, report: dict[str, object]) -> int:
    print(f"centerline-load: {name} ok")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load Busan centerline SHP into road network tables.")
    parser.add_argument(
        "--stage",
        choices=[
            "preflight",
            "extract-shp",
            "topology-audit",
            "load-db",
            "post-load-validate",
            "visualize-html",
            "full",
        ],
        default="preflight",
    )
    parser.add_argument("--visualize-limit", type=int, default=5000)
    args = parser.parse_args()

    if args.stage == "preflight":
        return print_report("preflight", centerline_loader.preflight_report())
    if args.stage == "extract-shp":
        return print_report("extract-shp", centerline_loader.extract_shp())
    if args.stage == "topology-audit":
        return print_report("topology-audit", centerline_loader.topology_audit())
    if args.stage == "load-db":
        return print_report("load-db", centerline_loader.load_db())
    if args.stage == "post-load-validate":
        return print_report("post-load-validate", centerline_loader.post_load_validate())
    if args.stage == "visualize-html":
        return print_report("visualize-html", centerline_loader.visualize_html(args.visualize_limit))
    if args.stage == "full":
        return print_report("full", centerline_loader.run_full())

    raise AssertionError(f"unsupported stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
