#!/usr/bin/env python3
"""Find playlist videos not yet successfully summarized."""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def scan(root: Path = ROOT) -> dict:
    config = load_json(root / "config.json", {})
    state = load_json(root / "data/state.json", {"seen": {}})
    cmd = ["yt-dlp", "--no-update", "--flat-playlist", "--dump-single-json", config["playlist_url"]]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "yt-dlp playlist scan failed")
    playlist = json.loads(proc.stdout)
    now = datetime.now(ZoneInfo(config.get("timezone", "Africa/Johannesburg"))).isoformat(timespec="seconds")
    seen = state.get("seen", {})
    pending = []
    for position, entry in enumerate(playlist.get("entries") or [], start=1):
        video_id = entry.get("id")
        if not video_id or video_id in seen:
            continue
        pending.append({
            "id": video_id,
            "title": entry.get("title") or "Untitled video",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration_seconds": int(entry.get("duration") or 0),
            "playlist_position": position,
            "detected_at": now,
        })
    result = {
        "playlist_id": playlist.get("id"),
        "playlist_title": playlist.get("title") or config.get("playlist_title"),
        "scanned_at": now,
        "new_count": len(pending),
        "pending": pending,
    }
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pending.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(scan(), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
