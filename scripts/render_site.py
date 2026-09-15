#!/usr/bin/env python3
"""Render the static companion site from the canonical video library."""
from __future__ import annotations
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def render(root: Path = ROOT) -> dict:
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    videos = json.loads((root / "data/videos.json").read_text(encoding="utf-8"))
    public = root / "public"
    public.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "site/index.html", public / "index.html")
    logo = root / "site/inspiretel-logo.png"
    if logo.exists():
        shutil.copy2(logo, public / "inspiretel-logo.png")
    payload = {
        "playlist": {"title": config["playlist_title"], "url": config["playlist_url"]},
        "schedule": config["scan_times"],
        "timezone": config["timezone"],
        "updated_at": datetime.now(ZoneInfo(config["timezone"])).isoformat(timespec="seconds"),
        "videos": videos,
    }
    (public / "videos.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"video_count": len(videos), "output": str(public)}


if __name__ == "__main__":
    print(json.dumps(render(), indent=2))
