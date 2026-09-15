#!/usr/bin/env python3
"""Validate summarized videos, merge them into the library, and mark them seen."""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"id", "title", "summary", "why_valuable", "chapters"}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def validate(item: dict) -> None:
    missing = REQUIRED - set(item)
    if missing:
        raise ValueError(f"{item.get('id', 'video')}: missing {sorted(missing)}")
    if not isinstance(item["chapters"], list) or not item["chapters"]:
        raise ValueError(f"{item['id']}: chapters must be a non-empty list")
    for chapter in item["chapters"]:
        if not {"start_seconds", "title", "description", "source"} <= set(chapter):
            raise ValueError(f"{item['id']}: malformed chapter")
        if chapter["source"] not in {"creator", "generated"}:
            raise ValueError(f"{item['id']}: invalid chapter source")
        description = str(chapter.get("description", "")).strip()
        sentence_count = len(re.findall(r"[.!?](?:\s|$)", description))
        if len(description) < 180 or sentence_count < 2:
            raise ValueError(f"{item['id']}: chapter descriptions must be detailed 2+ sentence paragraphs")


def merge(summary_path: Path, root: Path = ROOT) -> list[dict]:
    config = load(root / "config.json", {})
    now = datetime.now(ZoneInfo(config.get("timezone", "Africa/Johannesburg"))).isoformat(timespec="seconds")
    incoming = load(summary_path, [])
    if isinstance(incoming, dict):
        incoming = [incoming]
    pending_doc = load(root / "data/pending.json", {"pending": []})
    detected = {x["id"]: x.get("detected_at", now) for x in pending_doc.get("pending", [])}
    library = load(root / "data/videos.json", [])
    by_id = {v["id"]: v for v in library}
    state = load(root / "data/state.json", {"seen": {}})
    state.setdefault("seen", {})
    for item in incoming:
        validate(item)
        video_id = item["id"]
        previous = by_id.get(video_id, {})
        item["url"] = item.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        item["thumbnail"] = item.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        item["first_detected_at"] = previous.get("first_detected_at") or detected.get(video_id) or now
        item["summarized_at"] = now
        item["key_takeaways"] = item.get("key_takeaways", [])
        item["duration_seconds"] = int(item.get("duration_seconds") or 0)
        item["chapters"] = sorted(item["chapters"], key=lambda x: int(x["start_seconds"]))
        by_id[video_id] = item
        state["seen"][video_id] = item["first_detected_at"]
    merged = sorted(by_id.values(), key=lambda x: x.get("first_detected_at", ""), reverse=True)
    (root / "data/videos.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["last_completed_at"] = now
    (root / "data/state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return incoming


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_json", type=Path)
    args = parser.parse_args()
    merged = merge(args.summary_json)
    print(json.dumps({"merged_count": len(merged), "ids": [x["id"] for x in merged]}, indent=2))
