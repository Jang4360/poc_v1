from __future__ import annotations

import argparse
import base64
import csv
import json
import socket
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import websocket
from PIL import Image, ImageStat


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
TARGET_CSV = ROOT / "data" / "final" / "stairs" / "stair_roadview_validation_targets.csv"
REPORT_DIR = ROOT / "data" / "reports" / "stair_roadview_validation"
CAPTURE_ROOT = REPORT_DIR / "captures"
PROFILE_ROOT = REPORT_DIR / "chrome_profiles"
MANIFEST = REPORT_DIR / "capture_manifest.csv"
STATUS_JSON = REPORT_DIR / "capture_worker_status.json"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

CAPTURE_FIELDS = [
    "sourceId",
    "ufid",
    "districtGu",
    "name",
    "priority",
    "validationTargetGroup",
    "lat",
    "lng",
    "kakaoRoadviewUrl",
    "captureStatus",
    "attempts",
    "directionCount",
    "captureDir",
    "capturePaths",
    "elapsedSec",
    "maxBlackRatio",
    "maxDarkRatio",
    "imageWidth",
    "imageHeight",
    "firstBlackRatio",
    "firstDarkRatio",
    "firstWhiteRatio",
    "firstMeanRgb",
    "capturedAt",
    "error",
]

TERMINAL_STATUSES = {"CAPTURE_OK", "BLACK_OR_DARK_SCREEN", "CAPTURE_FAILED"}


class CdpClient:
    def __init__(self, ws: websocket.WebSocket):
        self.ws = ws
        self.next_id = 0

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
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def safe_id(source_id: str) -> str:
    return source_id.replace(":", "_").replace("/", "_").replace("\\", "_")


def append_manifest(row: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        exists = MANIFEST.exists()
        with MANIFEST.open("a", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CAPTURE_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow({field: row.get(field, "") for field in CAPTURE_FIELDS})


def write_status(**kwargs: Any) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps({"updatedAt": datetime.now().isoformat(), **kwargs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    return CdpClient(websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10.0))


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
    screenshot = client.send("Page.captureScreenshot", {"format": "png", "fromSurface": True, "captureBeyondViewport": False}, timeout=20.0)
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


def capture_once(row: dict[str, str], directions: int, wait_sec: float, attempt: int) -> dict[str, Any]:
    started = time.time()
    source_id = row["sourceId"]
    sid = safe_id(source_id)
    capture_dir = CAPTURE_ROOT / sid
    capture_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = PROFILE_ROOT / f"{sid}_attempt{attempt}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    process = launch_chrome(profile_dir, port)
    client: CdpClient | None = None
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
        paths: list[str] = []
        stats_list: list[dict[str, Any]] = []
        for direction in range(directions):
            path = capture_dir / f"dir_{direction:02d}.png"
            stats = save_screenshot(client, path)
            paths.append(str(path))
            stats_list.append(stats)
            if direction < directions - 1:
                drag_rotate(client)
                time.sleep(1.2)
        max_black = max(stats["blackRatio"] for stats in stats_list)
        max_dark = max(stats["darkRatio"] for stats in stats_list)
        first = stats_list[0]
        status = "CAPTURE_OK"
        if max_black > 0.55 or max_dark > 0.75:
            status = "BLACK_OR_DARK_SCREEN"
        return {
            "sourceId": source_id,
            "ufid": row.get("ufid", ""),
            "districtGu": row.get("districtGu", ""),
            "name": row.get("name", ""),
            "priority": row.get("priority", ""),
            "validationTargetGroup": row.get("validationTargetGroup", ""),
            "lat": row.get("lat", ""),
            "lng": row.get("lng", ""),
            "kakaoRoadviewUrl": row.get("kakaoRoadviewUrl", ""),
            "captureStatus": status,
            "attempts": attempt,
            "directionCount": directions,
            "captureDir": str(capture_dir),
            "capturePaths": ";".join(paths),
            "elapsedSec": round(time.time() - started, 1),
            "maxBlackRatio": max_black,
            "maxDarkRatio": max_dark,
            "imageWidth": first["imageWidth"],
            "imageHeight": first["imageHeight"],
            "firstBlackRatio": first["blackRatio"],
            "firstDarkRatio": first["darkRatio"],
            "firstWhiteRatio": first["whiteRatio"],
            "firstMeanRgb": first["meanRgb"],
            "capturedAt": datetime.now().isoformat(),
            "error": "",
        }
    except Exception as error:
        return {
            "sourceId": source_id,
            "ufid": row.get("ufid", ""),
            "districtGu": row.get("districtGu", ""),
            "name": row.get("name", ""),
            "priority": row.get("priority", ""),
            "validationTargetGroup": row.get("validationTargetGroup", ""),
            "lat": row.get("lat", ""),
            "lng": row.get("lng", ""),
            "kakaoRoadviewUrl": row.get("kakaoRoadviewUrl", ""),
            "captureStatus": "CAPTURE_FAILED",
            "attempts": attempt,
            "directionCount": directions,
            "captureDir": str(capture_dir),
            "capturePaths": "",
            "elapsedSec": round(time.time() - started, 1),
            "capturedAt": datetime.now().isoformat(),
            "error": str(error),
        }
    finally:
        try:
            client.ws.close() if client else None
        except Exception:
            pass
        process.kill()


def capture_with_retry(row: dict[str, str], directions: int, wait_sec: float, max_retries: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attempt in range(1, max_retries + 2):
        result = capture_once(row, directions=directions, wait_sec=wait_sec, attempt=attempt)
        if result["captureStatus"] == "CAPTURE_OK":
            return result
        time.sleep(1.0)
    return result


def processed_ids(retry_failed: bool) -> set[str]:
    ids: set[str] = set()
    for row in read_csv(MANIFEST):
        status = row.get("captureStatus", "")
        if retry_failed and status != "CAPTURE_OK":
            continue
        if status in TERMINAL_STATUSES:
            ids.add(row.get("sourceId", ""))
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Kakao roadview screenshots for stair validation.")
    parser.add_argument("--targets", type=Path, default=TARGET_CSV)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--directions", type=int, default=8)
    parser.add_argument("--wait-sec", type=float, default=12.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    targets = read_csv(args.targets)
    done = processed_ids(args.retry_failed)
    pending = [row for row in targets if row.get("sourceId") not in done]
    if args.limit:
        pending = pending[: args.limit]

    lock = threading.Lock()
    completed = 0
    write_status(state="RUNNING", totalTargets=len(targets), pending=len(pending), completed=completed)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(capture_with_retry, row, args.directions, args.wait_sec, args.max_retries)
            for row in pending
        ]
        for future in as_completed(futures):
            result = future.result()
            append_manifest(result, lock)
            completed += 1
            write_status(state="RUNNING", totalTargets=len(targets), pending=len(pending), completed=completed, lastResult=result)

    write_status(state="DONE", totalTargets=len(targets), pending=len(pending), completed=completed)


if __name__ == "__main__":
    main()
