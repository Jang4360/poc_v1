import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "graphhopper" / "scripts" / "build_pbf.sh"


def test_build_pbf_uses_osmium_and_writes_report(tmp_path: Path) -> None:
    fake_osmium = tmp_path / "osmium"
    fake_osmium.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "cat" ]]; then
  input="$2"
  output=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" ]]; then
      output="$2"
      break
    fi
    shift
  done
  cp "$input" "$output"
  exit 0
fi
if [[ "$1" == "fileinfo" ]]; then
  echo "File: $3"
  echo "Format: PBF"
  exit 0
fi
echo "unexpected command: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_osmium.chmod(0o755)
    source = tmp_path / "gangseo.osm"
    output = tmp_path / "gangseo.osm.pbf"
    report = tmp_path / "report.json"
    source.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"><node id="1" lat="35" lon="128" /></osm>\n',
        encoding="utf-8",
    )

    env = {**os.environ, "OSMIUM_BIN": str(fake_osmium)}
    result = subprocess.run(
        [str(SCRIPT), "--input", str(source), "--output", str(output), "--report-json", str(report)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert output.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["input"] == str(source)
    assert payload["output"] == str(output)
    assert payload["outputSizeBytes"] == source.stat().st_size
    assert "Format: PBF" in payload["fileinfo"]
    assert str(output) in result.stdout


def test_build_pbf_fails_without_osmium(tmp_path: Path) -> None:
    source = tmp_path / "gangseo.osm"
    report = tmp_path / "blocked.json"
    source.write_text("<osm version=\"0.6\" />\n", encoding="utf-8")
    env = {**os.environ, "OSMIUM_BIN": str(tmp_path / "missing-osmium")}

    result = subprocess.run(
        [
            str(SCRIPT),
            "--input",
            str(source),
            "--output",
            str(tmp_path / "out.pbf"),
            "--report-json",
            str(report),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 127
    assert "osmium executable not found" in result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["reason"] == "osmium executable not found"
