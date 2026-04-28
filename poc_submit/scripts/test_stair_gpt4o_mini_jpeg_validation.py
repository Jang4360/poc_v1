from __future__ import annotations

import argparse
import base64
import csv
import json
from pathlib import Path
from typing import Any

import requests
from PIL import Image


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
ENV_LOCAL = Path(r"C:\Users\SSAFY\workspace\S14P31E102\.env.local")
REPORT_DIR = ROOT / "data" / "reports" / "roadview_validation_test"
CAPTURE_RESULTS = REPORT_DIR / "roadview_capture_test_results.csv"
JPEG_DIR = REPORT_DIR / "gpt4o_mini_jpeg_inputs"
OUT_CSV = REPORT_DIR / "roadview_gpt4o_mini_test_results.csv"
OUT_JSON = REPORT_DIR / "roadview_gpt4o_mini_test_summary.json"
OPENAI_GMS_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/chat/completions"


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
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["sourceId"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{encoded}",
            "detail": "low",
        },
    }


def parse_capture_paths(row: dict[str, str]) -> list[Path]:
    raw = row.get("capturePaths") or row.get("capturePath") or ""
    return [Path(item) for item in raw.split(";") if item.strip()]


def classify_images(api_key: str, jpeg_paths: list[Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": USER_PROMPT}]
    for index, path in enumerate(jpeg_paths):
        content.append({"type": "text", "text": f"[image index {index}]"})
        content.append(image_part(path))

    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
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
    raw_text = data["choices"][0]["message"]["content"]
    return json.loads(raw_text), data.get("usage", {})


def aggregate_direction_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [result for result in results if result.get("status") != "ERROR"]
    if not usable:
        return {"status": "ERROR", "confidence": "LOW", "reason": "모든 방향 판정 실패", "visibleImageIndexes": []}
    confirmed = [result for result in usable if result.get("status") == "CONFIRMED_STAIR"]
    private = [result for result in usable if result.get("status") == "PRIVATE_OR_INTERNAL"]
    unclear = [result for result in usable if result.get("status") == "UNCLEAR"]
    no_roadview = [result for result in usable if result.get("status") == "NO_ROADVIEW"]

    if confirmed:
        return {
            "status": "CONFIRMED_STAIR",
            "confidence": "HIGH" if any(result.get("confidence") == "HIGH" for result in confirmed) else "MEDIUM",
            "reason": "1개 이상 방향에서 보행 계단 확인",
            "visibleImageIndexes": [result["directionIndex"] for result in confirmed],
        }
    if private:
        return {
            "status": "PRIVATE_OR_INTERNAL",
            "confidence": "MEDIUM",
            "reason": "사유지/시설 내부 계단 가능성",
            "visibleImageIndexes": [result["directionIndex"] for result in private],
        }
    if unclear:
        return {
            "status": "UNCLEAR",
            "confidence": "LOW",
            "reason": "일부 방향에서 판정 애매",
            "visibleImageIndexes": [result["directionIndex"] for result in unclear],
        }
    if len(no_roadview) == len(usable):
        return {"status": "NO_ROADVIEW", "confidence": "HIGH", "reason": "사용 가능한 로드뷰 없음", "visibleImageIndexes": []}
    return {"status": "NOT_STAIR", "confidence": "HIGH", "reason": "전체 방향에서 계단 미확인", "visibleImageIndexes": []}


def classify_row(api_key: str, row: dict[str, str], max_width: int, quality: int, max_images: int) -> dict[str, Any]:
    source_id = row.get("sourceId", "")
    safe_id = source_id.replace(":", "_").replace("/", "_")
    capture_paths = parse_capture_paths(row)[:max_images]
    jpeg_paths: list[Path] = []
    for index, capture_path in enumerate(capture_paths):
        jpeg_path = JPEG_DIR / f"{safe_id}_img{index:02d}_{max_width}w_q{quality}.jpg"
        jpeg_paths.append(compress_to_jpeg(capture_path, jpeg_path, max_width=max_width, quality=quality))

    payload_bytes = sum(path.stat().st_size for path in jpeg_paths)
    try:
        direction_results: list[dict[str, Any]] = []
        prompt_tokens = 0
        completion_tokens = 0
        for index, jpeg_path in enumerate(jpeg_paths):
            result, usage = classify_images(api_key, [jpeg_path])
            result["directionIndex"] = index
            direction_results.append(result)
            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        result = aggregate_direction_results(direction_results)
        return {
            "sourceId": source_id,
            "targetGroup": row.get("targetGroup", ""),
            "priority": row.get("priority", ""),
            "imageCount": len(jpeg_paths),
            "jpegTotalBytes": payload_bytes,
            "validationStatus": result.get("status", "UNCLEAR"),
            "validationConfidence": result.get("confidence", "LOW"),
            "validationReason": result.get("reason", ""),
            "visibleImageIndexes": json.dumps(result.get("visibleImageIndexes", []), ensure_ascii=False),
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "directionResults": json.dumps(direction_results, ensure_ascii=False),
            "error": "",
        }
    except Exception as error:
        return {
            "sourceId": source_id,
            "targetGroup": row.get("targetGroup", ""),
            "priority": row.get("priority", ""),
            "imageCount": len(jpeg_paths),
            "jpegTotalBytes": payload_bytes,
            "validationStatus": "ERROR",
            "validationConfidence": "LOW",
            "validationReason": "",
            "visibleImageIndexes": "[]",
            "promptTokens": "",
            "completionTokens": "",
            "directionResults": "[]",
            "error": str(error),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate roadview captures with GMS gpt-4o-mini vision.")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--quality", type=int, default=55)
    parser.add_argument("--max-images", type=int, default=8)
    args = parser.parse_args()

    api_key = load_gms_key()
    rows = [row for row in read_csv(CAPTURE_RESULTS) if row.get("captureStatus") == "CAPTURE_OK"][: args.limit]
    results = [
        classify_row(api_key, row, max_width=args.max_width, quality=args.quality, max_images=args.max_images)
        for row in rows
    ]
    write_csv(OUT_CSV, results)
    summary = {
        "total": len(results),
        "settings": {"model": "gpt-4o-mini", "maxWidth": args.max_width, "quality": args.quality, "maxImages": args.max_images},
        "outputs": {"csv": str(OUT_CSV), "jpegDir": str(JPEG_DIR)},
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
