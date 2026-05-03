#!/usr/bin/env bash
set -euo pipefail

INPUT="graphhopper/data/gangseo.osm"
OUTPUT="graphhopper/data/gangseo.osm.pbf"
REPORT_JSON="runtime/graphhopper/pbf/gangseo_pbf_report.json"
OSMIUM_BIN="${OSMIUM_BIN:-osmium}"

usage() {
  cat <<'EOF'
Usage: graphhopper/scripts/build_pbf.sh [options]

Options:
  --input PATH        OSM XML input path. Default: graphhopper/data/gangseo.osm
  --output PATH       OSM PBF output path. Default: graphhopper/data/gangseo.osm.pbf
  --report-json PATH  Report JSON path. Default: runtime/graphhopper/pbf/gangseo_pbf_report.json
  --help              Show this help.

Environment:
  OSMIUM_BIN          osmium executable path. Default: osmium
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUT="${2:?--input requires a path}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:?--output requires a path}"
      shift 2
      ;;
    --report-json)
      REPORT_JSON="${2:?--report-json requires a path}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "build_pbf: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$INPUT" ]]; then
  echo "build_pbf: input OSM XML not found: $INPUT" >&2
  exit 1
fi

mkdir -p "$(dirname "$REPORT_JSON")"

if ! command -v "$OSMIUM_BIN" >/dev/null 2>&1; then
  export BUILD_PBF_INPUT="$INPUT"
  export BUILD_PBF_OUTPUT="$OUTPUT"
  export BUILD_PBF_REPORT="$REPORT_JSON"
  export BUILD_PBF_OSMIUM_BIN="$OSMIUM_BIN"
  python - <<'PY'
import json
import os
from pathlib import Path

input_path = Path(os.environ["BUILD_PBF_INPUT"])
report_path = Path(os.environ["BUILD_PBF_REPORT"])
report = {
    "status": "blocked",
    "reason": "osmium executable not found",
    "input": str(input_path),
    "output": os.environ["BUILD_PBF_OUTPUT"],
    "osmiumBin": os.environ["BUILD_PBF_OSMIUM_BIN"],
    "inputSizeBytes": input_path.stat().st_size,
}
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  cat >&2 <<EOF
build_pbf: osmium executable not found.
Install osmium-tool or set OSMIUM_BIN to an existing osmium executable, then rerun:
  OSMIUM_BIN=/path/to/osmium graphhopper/scripts/build_pbf.sh --input "$INPUT" --output "$OUTPUT"
EOF
  exit 127
fi

mkdir -p "$(dirname "$OUTPUT")"

"$OSMIUM_BIN" cat "$INPUT" -o "$OUTPUT" --overwrite

if [[ ! -s "$OUTPUT" ]]; then
  echo "build_pbf: output PBF was not created or is empty: $OUTPUT" >&2
  exit 1
fi

FILEINFO="$("$OSMIUM_BIN" fileinfo -e "$OUTPUT")"
export BUILD_PBF_INPUT="$INPUT"
export BUILD_PBF_OUTPUT="$OUTPUT"
export BUILD_PBF_REPORT="$REPORT_JSON"
export BUILD_PBF_FILEINFO="$FILEINFO"

python - <<'PY'
import json
import os
from pathlib import Path

input_path = Path(os.environ["BUILD_PBF_INPUT"])
output_path = Path(os.environ["BUILD_PBF_OUTPUT"])
report_path = Path(os.environ["BUILD_PBF_REPORT"])
fileinfo = os.environ["BUILD_PBF_FILEINFO"]
report = {
    "input": str(input_path),
    "output": str(output_path),
    "inputSizeBytes": input_path.stat().st_size,
    "outputSizeBytes": output_path.stat().st_size,
    "fileinfo": fileinfo.splitlines(),
}
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: report[k] for k in ("input", "output", "inputSizeBytes", "outputSizeBytes")}, ensure_ascii=False, indent=2))
PY
