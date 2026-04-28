from __future__ import annotations

import argparse
import base64
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
ENV_LOCAL = Path(r"C:\Users\SSAFY\workspace\S14P31E102\.env.local")
REPORT_DIR = ROOT / "data" / "reports" / "stair_roadview_validation"
MANIFEST = REPORT_DIR / "capture_manifest.csv"
JPEG_ROOT = REPORT_DIR / "jpeg_inputs"
RESULTS_CSV = REPORT_DIR / "ai_validation_results.csv"
STATUS_JSON = REPORT_DIR / "ai_validation_worker_status.json"
OPENAI_GMS_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/chat/completions"

RESULT_FIELDS = [
    "sourceId",
    "ufid",
    "districtGu",
    "name",
    "priority",
    "validationTargetGroup",
    "validationStatus",
    "validationConfidence",
    "validationReason",
    "visibleDirectionIndexes",
    "directionCount",
    "jpegTotalBytes",
    "promptTokens",
    "completionTokens",
    "directionResults",
    "validatedAt",
    "error",
]

SYSTEM_PROMPT = (
    "You are a strict roadview image classifier for wheelchair and walking accessibility data. "
    "Return only valid JSON. No markdown. No text outside JSON."
)

USER_PROMPT = """Analyze this Kakao roadview image from one candidate stair location.
Decide whether an outdoor stairway that pedestrians can actually use is visible.

Return exactly this JSON schema:
{
  "status": "CONFIRMED_STAIR|NOT_STAIR|PRIVATE_OR_INTERNAL|NO_ROADVIEW|UNCLEAR",
  "confidence": "HIGH|MEDIUM|LOW",
  "reason": "short Korean reason",
  "visibleImageIndexes": [0]
}

Rules:
- CONFIRMED_STAIR: an outdoor pedestrian stairway is clearly visible.
- NOT_STAIR: roadview is valid, but no stairway is visible.
- PRIVATE_OR_INTERNAL: stairway appears to be inside/for a private building, apartment, construction site, or facility-only area.
- NO_ROADVIEW: only if the image is black/blank/map UI only, or the panorama is not usable.
- If a road, sidewalk, trees, buildings, cars, or landscape are visible, the image is usable roadview. In that case choose NOT_STAIR when no stairway is visible.
- UNCLEAR: image is usable but stair presence/public usability is ambiguous.
- visibleImageIndexes must be [] unless a stairway is visible.
"""


def load_gms_key() -> str:
    for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("GMS_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise RuntimeError(f"GMS_KEY not found: {ENV_LOCAL}")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def append_result(row: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        exists = RESULTS_CSV.exists()
        with RESULTS_CSV.open("a", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=RESULT_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow({field: row.get(field, "") for field in RESULT_FIELDS})


def write_status(**kwargs: Any) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps({"updatedAt": datetime.now().isoformat(), **kwargs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_id(source_id: str) -> str:
    return source_id.replace(":", "_").replace("/", "_").replace("\\", "_")


def capture_paths(row: dict[str, str]) -> list[Path]:
    raw = row.get("capturePaths", "")
    return [Path(item) for item in raw.split(";") if item.strip()]


def compress_to_jpeg(source: Path, output: Path, max_width: int, quality: int) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(source).convert("RGB")
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, int(image.height * ratio)), Image.Resampling.LANCZOS)
    image.save(output, "JPEG", quality=quality, optimize=True)
    return output


def image_part(path: Path) -> dict[str, Any]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "low"}}


def call_gpt4o_mini(api_key: str, image_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [{"type": "text", "text": USER_PROMPT}, image_part(image_path)]},
        ],
        "temperature": 0,
        "max_tokens": 180,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        OPENAI_GMS_URL,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    return json.loads(data["choices"][0]["message"]["content"]), data.get("usage", {})


def call_with_retry(api_key: str, image_path: Path, retries: int) -> tuple[dict[str, Any], dict[str, Any]]:
    wait = 2.0
    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            return call_gpt4o_mini(api_key, image_path)
        except Exception as error:
            last_error = error
            time.sleep(wait)
            wait *= 1.7
    raise RuntimeError(str(last_error))


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [result for result in results if result.get("status") != "ERROR"]
    if not usable:
        return {"status": "ERROR", "confidence": "LOW", "reason": "모든 방향 판정 실패", "visibleDirectionIndexes": []}
    confirmed = [result for result in usable if result.get("status") == "CONFIRMED_STAIR"]
    private = [result for result in usable if result.get("status") == "PRIVATE_OR_INTERNAL"]
    unclear = [result for result in usable if result.get("status") == "UNCLEAR"]
    no_roadview = [result for result in usable if result.get("status") == "NO_ROADVIEW"]
    if confirmed:
        return {
            "status": "CONFIRMED_STAIR",
            "confidence": "HIGH" if any(result.get("confidence") == "HIGH" for result in confirmed) else "MEDIUM",
            "reason": "1개 이상 방향에서 보행 계단 확인",
            "visibleDirectionIndexes": [result["directionIndex"] for result in confirmed],
        }
    if private:
        return {
            "status": "PRIVATE_OR_INTERNAL",
            "confidence": "MEDIUM",
            "reason": "사유지/시설 내부 계단 가능성",
            "visibleDirectionIndexes": [result["directionIndex"] for result in private],
        }
    if unclear:
        return {
            "status": "UNCLEAR",
            "confidence": "LOW",
            "reason": "일부 방향에서 판정 애매",
            "visibleDirectionIndexes": [result["directionIndex"] for result in unclear],
        }
    if len(no_roadview) == len(usable):
        return {"status": "NO_ROADVIEW", "confidence": "HIGH", "reason": "사용 가능한 로드뷰 없음", "visibleDirectionIndexes": []}
    return {"status": "NOT_STAIR", "confidence": "HIGH", "reason": "전체 방향에서 계단 미확인", "visibleDirectionIndexes": []}


def validate_capture(api_key: str, row: dict[str, str], max_width: int, quality: int, retries: int) -> dict[str, Any]:
    sid = safe_id(row["sourceId"])
    source_paths = capture_paths(row)
    jpeg_paths: list[Path] = []
    for index, source_path in enumerate(source_paths):
        jpeg_path = JPEG_ROOT / sid / f"dir_{index:02d}_{max_width}w_q{quality}.jpg"
        jpeg_paths.append(compress_to_jpeg(source_path, jpeg_path, max_width=max_width, quality=quality))
    direction_results: list[dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    for index, jpeg_path in enumerate(jpeg_paths):
        try:
            result, usage = call_with_retry(api_key, jpeg_path, retries=retries)
            result["directionIndex"] = index
            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        except Exception as error:
            result = {"status": "ERROR", "confidence": "LOW", "reason": str(error), "visibleImageIndexes": [], "directionIndex": index}
        direction_results.append(result)
    merged = aggregate(direction_results)
    return {
        "sourceId": row.get("sourceId", ""),
        "ufid": row.get("ufid", ""),
        "districtGu": row.get("districtGu", ""),
        "name": row.get("name", ""),
        "priority": row.get("priority", ""),
        "validationTargetGroup": row.get("validationTargetGroup", ""),
        "validationStatus": merged["status"],
        "validationConfidence": merged["confidence"],
        "validationReason": merged["reason"],
        "visibleDirectionIndexes": json.dumps(merged.get("visibleDirectionIndexes", []), ensure_ascii=False),
        "directionCount": len(jpeg_paths),
        "jpegTotalBytes": sum(path.stat().st_size for path in jpeg_paths),
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "directionResults": json.dumps(direction_results, ensure_ascii=False),
        "validatedAt": datetime.now().isoformat(),
        "error": "",
    }


def processed_ids() -> set[str]:
    return {row.get("sourceId", "") for row in read_csv(RESULTS_CSV) if row.get("sourceId")}


def valid_capture_rows() -> list[dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in read_csv(MANIFEST):
        if row.get("captureStatus") == "CAPTURE_OK":
            latest[row["sourceId"]] = row
    return list(latest.values())


def process_batch(api_key: str, rows: list[dict[str, str]], workers: int, max_width: int, quality: int, retries: int) -> int:
    lock = threading.Lock()
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(validate_capture, api_key, row, max_width, quality, retries) for row in rows]
        for future in as_completed(futures):
            append_result(future.result(), lock)
            completed += 1
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate captured stair roadviews with GMS gpt-4o-mini vision.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-width", type=int, default=480)
    parser.add_argument("--quality", type=int, default=45)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-sec", type=float, default=20.0)
    parser.add_argument("--idle-exit-sec", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JPEG_ROOT.mkdir(parents=True, exist_ok=True)
    api_key = load_gms_key()
    idle_started: float | None = None
    total_completed = 0
    while True:
        done = processed_ids()
        rows = [row for row in valid_capture_rows() if row.get("sourceId") not in done]
        if args.limit:
            rows = rows[: args.limit]
        write_status(state="RUNNING", pending=len(rows), completedThisRun=total_completed, processedTotal=len(done))
        if rows:
            idle_started = None
            total_completed += process_batch(api_key, rows, args.workers, args.max_width, args.quality, args.retries)
        elif not args.watch:
            break
        else:
            if idle_started is None:
                idle_started = time.time()
            if args.idle_exit_sec and time.time() - idle_started > args.idle_exit_sec:
                break
            time.sleep(args.poll_sec)
    write_status(state="DONE", completedThisRun=total_completed, processedTotal=len(processed_ids()))


if __name__ == "__main__":
    main()
