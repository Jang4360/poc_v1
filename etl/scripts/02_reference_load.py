#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import reference_loader


def print_report(name: str, report: dict[str, object]) -> int:
    print(f"reference-load: {name} ok")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load CSV reference and accessibility data into IeumGil tables.")
    parser.add_argument(
        "--stage",
        choices=[
            "diff-places",
            "dry-run",
            "load-places",
            "load-place-accessibility",
            "load-audio-signals",
            "load-crosswalks",
            "load-subway-elevators",
            "load-low-floor-buses",
            "slope-report",
            "load-slope-analysis",
            "continuous-manifest",
            "continuous-centerline-compare",
            "load-continuous-width-surface",
            "load-continuous-stairs",
            "load-continuous-evidence-layers",
            "ensure-reference-schema",
            "load-all",
            "post-load-validate",
            "counts",
        ],
        default="dry-run",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.stage == "diff-places":
        return print_report("diff-places", reference_loader.diff_place_csvs())
    if args.stage == "dry-run":
        return print_report("dry-run", reference_loader.run_all(dry_run=True))
    if args.stage == "load-places":
        return print_report("load-places", reference_loader.load_places(dry_run=args.dry_run))
    if args.stage == "load-place-accessibility":
        return print_report("load-place-accessibility", reference_loader.load_place_accessibility(dry_run=args.dry_run))
    if args.stage == "load-audio-signals":
        return print_report("load-audio-signals", reference_loader.load_audio_signals(dry_run=args.dry_run))
    if args.stage == "load-crosswalks":
        return print_report("load-crosswalks", reference_loader.load_crosswalks(dry_run=args.dry_run))
    if args.stage == "load-subway-elevators":
        return print_report("load-subway-elevators", reference_loader.load_subway_elevators(dry_run=args.dry_run))
    if args.stage == "load-low-floor-buses":
        return print_report("load-low-floor-buses", reference_loader.load_low_floor_bus_routes(dry_run=args.dry_run))
    if args.stage == "slope-report":
        return print_report("slope-report", reference_loader.slope_analysis_report())
    if args.stage == "load-slope-analysis":
        return print_report("load-slope-analysis", reference_loader.load_slope_analysis(dry_run=args.dry_run))
    if args.stage == "continuous-manifest":
        return print_report("continuous-manifest", reference_loader.continuous_map_manifest())
    if args.stage == "continuous-centerline-compare":
        return print_report("continuous-centerline-compare", reference_loader.continuous_centerline_compare())
    if args.stage == "load-continuous-width-surface":
        return print_report(
            "load-continuous-width-surface",
            reference_loader.load_continuous_width_surface(dry_run=args.dry_run),
        )
    if args.stage == "load-continuous-stairs":
        return print_report("load-continuous-stairs", reference_loader.load_continuous_stairs(dry_run=args.dry_run))
    if args.stage == "load-continuous-evidence-layers":
        return print_report(
            "load-continuous-evidence-layers",
            reference_loader.load_continuous_evidence_layers(dry_run=args.dry_run),
        )
    if args.stage == "ensure-reference-schema":
        reference_loader.ensure_reference_schema()
        return print_report("ensure-reference-schema", {"status": "ok"})
    if args.stage == "load-all":
        return print_report("load-all", reference_loader.run_all(dry_run=args.dry_run))
    if args.stage == "post-load-validate":
        return print_report("post-load-validate", reference_loader.post_load_validate())
    if args.stage == "counts":
        return print_report("counts", reference_loader.db_counts())

    raise AssertionError(f"unsupported stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
