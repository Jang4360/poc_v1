from __future__ import annotations

import argparse
import base64
import csv
import json
import socket
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket
from PIL import Image, ImageStat


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
REPORT_DIR = ROOT / "data" / "reports" / "roadview_validation_test"
CAPTURE_DIR = REPORT_DIR / "captures"
PROFILE_ROOT = REPORT_DIR / "chrome_profiles"
MANUAL_REVIEW = ROOT / "data" / "final" / "stairs" / "stair_second_pass_manual_review.csv"
LIKELY_ADOPT = ROOT / "data" / "final" / "stairs" / "stair_second_pass_likely_adopt.csv"
OUT_CSV = REPORT_DIR / "roadview_capture_test_results.csv"
OUT_JSON = REPORT_DIR / "roadview_capture_test_summary.json"


@dataclass
class CdpClient:
    ws: websocket.WebSocket
    next_id: int = 0

    def send(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        self.ws.settimeout(timeout)
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"{method} failed: {message['error']}")
            return message.get("result", {})


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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_json(url: str, timeout_sec: float = 10.0) -> Any:
    deadline = time.time() + timeout_sec
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"CDP endpoint not ready: {url} ({last_error})")


def launch_chrome(profile_dir: Path, port: int) -> subprocess.Popen:
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(CHROME),
        "--headless=new",
        "--no-first-run",
        "--disable-extensions",
        "--hide-scrollbars",
        "--ignore-gpu-blocklist",
        "--enable-webgl",
        "--use-gl=angle",
        "--use-angle=d3d11",
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--window-size=1280,720",
        "about:blank",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def connect_cdp(port: int) -> CdpClient:
    tabs = wait_json(f"http://127.0.0.1:{port}/json", timeout_sec=10.0)
    page = next(tab for tab in tabs if tab.get("type") == "page")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10.0)
    return CdpClient(ws=ws)


def image_stats(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    pixels = list(image.getdata())
    total = len(pixels)
    black = sum(1 for r, g, b in pixels if r < 20 and g < 20 and b < 20)
    dark = sum(1 for r, g, b in pixels if r < 45 and g < 45 and b < 45)
    white = sum(1 for r, g, b in pixels if r > 245 and g > 245 and b > 245)
    mean = ImageStat.Stat(image).mean
    return {
        "imageWidth": image.size[0],
        "imageHeight": image.size[1],
        "blackRatio": round(black / total, 5),
        "darkRatio": round(dark / total, 5),
        "whiteRatio": round(white / total, 5),
        "meanRgb": ",".join(str(round(value, 1)) for value in mean),
    }


def save_screenshot(client: CdpClient, path: Path) -> dict[str, Any]:
    screenshot = client.send(
        "Page.captureScreenshot",
        {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
        timeout=20.0,
    )
    path.write_bytes(base64.b64decode(screenshot["data"]))
    return image_stats(path)


def drag_rotate(client: CdpClient) -> None:
    y = 360
    start_x = 760
    end_x = 360
    client.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": start_x, "y": y, "button": "left", "clickCount": 1})
    for step in range(1, 7):
        x = start_x + (end_x - start_x) * step / 6
        client.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left"})
        time.sleep(0.05)
    client.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": end_x, "y": y, "button": "left", "clickCount": 1})


def capture_roadview(row: dict[str, str], index: int, wait_sec: float, directions: int) -> dict[str, Any]:
    source_id = row.get("sourceId", f"row-{index}")
    safe_id = source_id.replace(":", "_").replace("/", "_")
    capture_path = CAPTURE_DIR / f"{index:03d}_{safe_id}.png"
    profile_dir = PROFILE_ROOT / f"profile_{index:03d}_{safe_id}"
    port = free_port()
    process = launch_chrome(profile_dir, port)
    client: CdpClient | None = None
    started = time.time()
    try:
        wait_json(f"http://127.0.0.1:{port}/json/version", timeout_sec=10.0)
        client = connect_cdp(port)
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.navigate", {"url": row["kakaoRoadviewUrl"]}, timeout=10.0)
        time.sleep(wait_sec)
        try:
            client.send("Page.stopLoading", timeout=3.0)
        except Exception:
            pass
        capture_paths: list[str] = []
        stats_list: list[dict[str, Any]] = []
        for direction_index in range(directions):
            direction_path = (
                CAPTURE_DIR / f"{index:03d}_{safe_id}_dir{direction_index:02d}.png"
                if directions > 1
                else capture_path
            )
            stats = save_screenshot(client, direction_path)
            capture_paths.append(str(direction_path))
            stats_list.append(stats)
            if direction_index < directions - 1:
                drag_rotate(client)
                time.sleep(1.2)

        first_stats = stats_list[0]
        max_black = max(stats["blackRatio"] for stats in stats_list)
        max_dark = max(stats["darkRatio"] for stats in stats_list)
        capture_status = "CAPTURE_OK"
        if max_black > 0.55 or max_dark > 0.75:
            capture_status = "BLACK_OR_DARK_SCREEN"
        return {
            "sourceId": source_id,
            "ufid": row.get("ufid", ""),
            "districtGu": row.get("districtGu", ""),
            "name": row.get("name", ""),
            "priority": row.get("priority", ""),
            "targetGroup": row.get("targetGroup", ""),
            "lat": row.get("lat", ""),
            "lng": row.get("lng", ""),
            "kakaoRoadviewUrl": row.get("kakaoRoadviewUrl", ""),
            "captureStatus": capture_status,
            "capturePath": capture_paths[0],
            "capturePaths": ";".join(capture_paths),
            "directionCount": directions,
            "elapsedSec": round(time.time() - started, 1),
            "maxBlackRatio": max_black,
            "maxDarkRatio": max_dark,
            **first_stats,
        }
    except Exception as error:
        return {
            "sourceId": source_id,
            "ufid": row.get("ufid", ""),
            "districtGu": row.get("districtGu", ""),
            "name": row.get("name", ""),
            "priority": row.get("priority", ""),
            "targetGroup": row.get("targetGroup", ""),
            "lat": row.get("lat", ""),
            "lng": row.get("lng", ""),
            "kakaoRoadviewUrl": row.get("kakaoRoadviewUrl", ""),
            "captureStatus": "CAPTURE_FAILED",
            "capturePath": str(capture_path),
            "elapsedSec": round(time.time() - started, 1),
            "error": str(error),
        }
    finally:
        try:
            client.ws.close() if client else None
        except Exception:
            pass
        process.kill()


def build_test_rows(limit: int) -> list[dict[str, str]]:
    manual_rows = read_csv(MANUAL_REVIEW)
    p4_rows = [row for row in read_csv(LIKELY_ADOPT) if row.get("priority") == "P4"]
    for row in manual_rows:
        row["targetGroup"] = "MANUAL_REVIEW"
    for row in p4_rows:
        row["targetGroup"] = "P4_LIKELY_ADOPT"

    def sort_key(row: dict[str, str]) -> tuple[int, str]:
        district = row.get("districtGu", "")
        return (0 if "해운대" in district else 1, row.get("sourceId", ""))

    selected: list[dict[str, str]] = []
    selected.extend(sorted(manual_rows, key=sort_key)[: max(1, limit // 2)])
    selected.extend(sorted(p4_rows, key=sort_key)[: limit - len(selected)])
    return selected[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Kakao roadview capture smoke test for stair validation.")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--wait-sec", type=float, default=12.0)
    parser.add_argument("--directions", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    rows = build_test_rows(args.limit)
    jobs = [(row, index + 1, args.wait_sec, max(1, args.directions)) for index, row in enumerate(rows)]
    worker_count = max(1, args.workers)
    if worker_count == 1:
        results = [capture_roadview(*job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(lambda job: capture_roadview(*job), jobs))
    write_csv(OUT_CSV, results)
    summary = {
        "total": len(results),
        "statusCounts": dict(csv_counter(row["captureStatus"] for row in results)),
        "outputs": {"csv": str(OUT_CSV), "captureDir": str(CAPTURE_DIR)},
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def csv_counter(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


if __name__ == "__main__":
    main()
