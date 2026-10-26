#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3"]
# ///
"""Read-only MCP server that lets Claude search and read the VidBot library.

Runs over stdio for Claude Desktop / Claude Code. Reads the local checkout's
data/ when present (always current on the machine that runs the scans), and
falls back to the public GitHub copy otherwise.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

if __package__:
    from .merge_summary import clean_executive_summary
else:
    from merge_summary import clean_executive_summary

ROOT = Path(os.environ.get("VIDBOT_ROOT") or Path(__file__).resolve().parents[1])
RAW_BASE = os.environ.get(
    "VIDBOT_RAW_BASE", "https://raw.githubusercontent.com/inspiretelapps/vidbot-library/main"
)
REMOTE_TTL_SECONDS = 600
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|^)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
TRANSCRIPT_PREFERENCE = (".transcript.txt", ".en.txt", ".captions.json", ".transcript.json")
STOPWORDS = {"a", "an", "and", "are", "for", "how", "in", "is", "it", "of", "on", "or", "the", "to", "what", "with"}


class Library:
    """Loads videos.json and transcripts, reloading when the source changes."""

    def __init__(self, root: Path = ROOT, raw_base: str = RAW_BASE):
        self.root = root
        self.raw_base = raw_base.rstrip("/")
        self._videos: list[dict] = []
        self._stamp: float | None = None
        self._remote_listing: list[str] | None = None

    @property
    def local(self) -> bool:
        return (self.root / "data/videos.json").is_file()

    def _fetch(self, rel: str) -> bytes:
        with urllib.request.urlopen(f"{self.raw_base}/{rel}", timeout=30) as response:
            return response.read()

    def videos(self) -> list[dict]:
        if self.local:
            path = self.root / "data/videos.json"
            stamp = path.stat().st_mtime
            if stamp != self._stamp:
                self._videos, self._stamp = json.loads(path.read_text(encoding="utf-8")), stamp
        elif self._stamp is None or time.time() - self._stamp > REMOTE_TTL_SECONDS:
            self._videos, self._stamp = json.loads(self._fetch("data/videos.json")), time.time()
            self._remote_listing = None
        return self._videos

    def find(self, video: str) -> dict:
        match = VIDEO_ID.search(video.strip())
        wanted = match[1] if match else video.strip()
        for item in self.videos():
            if item["id"] == wanted:
                return item
        lowered = video.strip().lower()
        titled = [item for item in self.videos() if lowered and lowered in item["title"].lower()]
        if len(titled) == 1:
            return titled[0]
        raise ValueError(f"No single library video matches {video!r}; use search_videos to find its id.")

    def transcript_files(self, video_id: str) -> list[str]:
        if self.local:
            folder = self.root / "data/transcripts"
            names = [p.name for p in folder.glob(f"{glob_escape(video_id)}.*")] if folder.is_dir() else []
        else:
            if self._remote_listing is None:
                api = "https://api.github.com/repos/inspiretelapps/vidbot-library/contents/data/transcripts"
                try:
                    with urllib.request.urlopen(api, timeout=30) as response:
                        self._remote_listing = [entry["name"] for entry in json.load(response)]
                except OSError:
                    self._remote_listing = []
            names = [n for n in self._remote_listing if n.startswith(f"{video_id}.")]
        ranked = [n for suffix in TRANSCRIPT_PREFERENCE for n in sorted(names) if n.endswith(suffix)]
        return ranked

    def read_transcript(self, name: str) -> str:
        if self.local:
            return (self.root / "data/transcripts" / name).read_text(encoding="utf-8")
        return self._fetch(f"data/transcripts/{name}").decode("utf-8")


def glob_escape(text: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", text)


def as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def seconds_label(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60:02d}:{rest % 60:02d}"


def parse_clock(text: str) -> float:
    parts = [float(p) for p in text.split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def jump_url(item: dict, seconds: float) -> str:
    return f"https://www.youtube.com/watch?v={item['id']}&t={int(seconds)}s"


def transcript_lines(name: str, text: str) -> list[tuple[float, str]]:
    """Normalise the library's transcript formats to (start_seconds, text) lines."""
    if name.endswith(".txt"):
        lines = []
        for raw in text.splitlines():
            match = re.match(r"\s*\[?(\d{1,2}(?::\d{2}){1,2})\]?\s+(.*)", raw)
            if match:
                lines.append((parse_clock(match[1]), match[2].strip()))
            elif raw.strip() and lines:
                lines[-1] = (lines[-1][0], f"{lines[-1][1]} {raw.strip()}")
        return lines
    data = json.loads(text)
    if isinstance(data.get("segments"), list):
        return [(float(s.get("start", 0)), str(s.get("text", "")).strip()) for s in data["segments"]]
    if isinstance(data.get("events"), list):
        return [
            (e.get("tStartMs", 0) / 1000, "".join(seg.get("utf8", "") for seg in e["segs"]).strip())
            for e in data["events"] if e.get("segs")
        ]
    if data.get("timestamped_text"):
        return transcript_lines(".txt", data["timestamped_text"])
    if data.get("full_text"):
        return [(0.0, data["full_text"])]
    return []


def brief(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item["title"],
        "channel": item.get("channel", ""),
        "first_detected": str(item.get("first_detected_at", ""))[:10],
        "duration": seconds_label(float(item.get("duration_seconds") or 0)),
        "url": item.get("url") or f"https://www.youtube.com/watch?v={item['id']}",
    }


def takeaways(item: dict) -> list[str]:
    return as_list(item.get("quick_takeaways")) or as_list(item.get("key_takeaways"))


def filtered(videos: list[dict], channel: str | None, since: str | None, before: str | None) -> list[dict]:
    out = []
    for item in videos:
        detected = str(item.get("first_detected_at", ""))[:10]
        if channel and channel.lower() not in str(item.get("channel", "")).lower():
            continue
        if since and detected < since:
            continue
        if before and detected >= before:
            continue
        out.append(item)
    return out


def search_fields(item: dict) -> list[tuple[str, float, str]]:
    fields = [("title", 5.0, item["title"]), ("channel", 2.0, str(item.get("channel", "")))]
    fields += [("takeaway", 3.0, t) for t in takeaways(item)]
    fields += [("key_takeaway", 2.0, t) for t in as_list(item.get("key_takeaways"))]
    fields += [("summary", 1.5, p) for p in re.split(r"\n\s*\n", str(item.get("summary", ""))) if p.strip()]
    for chapter in as_list(item.get("chapters")):
        fields.append(("chapter", 1.0, f"{chapter.get('title', '')}: {chapter.get('description', '')}"))
    return fields


def score(item: dict, query: str) -> tuple[float, str, str]:
    phrase = query.lower().strip()
    terms = [t for t in re.findall(r"[a-z0-9][a-z0-9.+#-]*", phrase) if t not in STOPWORDS] or [phrase]
    total, best, best_field, matched = 0.0, (0.0, "", ""), "", set()
    for field, weight, text in search_fields(item):
        lowered = text.lower()
        hits = [t for t in terms if t in lowered]
        if not hits:
            continue
        matched.update(hits)
        gained = weight * len(hits) + (weight * 2 if len(terms) > 1 and phrase in lowered else 0)
        total += gained
        if gained > best[0]:
            best = (gained, field, text)
    if not total:
        return 0.0, "", ""
    total *= len(matched) / len(terms)
    return total, best[1], snippet(best[2], terms)


def snippet(text: str, terms: list[str], width: int = 320) -> str:
    lowered = text.lower()
    positions = [lowered.find(t) for t in terms if t in lowered]
    start = max(0, min(positions) - width // 3) if positions else 0
    clip = text[start:start + width].strip()
    return ("…" if start else "") + clip + ("…" if start + width < len(text) else "")


def library_overview(lib: Library) -> dict:
    videos = lib.videos()
    channels: dict[str, int] = {}
    for item in videos:
        channels[item.get("channel", "")] = channels.get(item.get("channel", ""), 0) + 1
    dates = sorted(str(v.get("first_detected_at", ""))[:10] for v in videos)
    newest = sorted(videos, key=lambda v: v.get("first_detected_at", ""), reverse=True)[:10]
    return {
        "source": "local checkout" if lib.local else lib.raw_base,
        "video_count": len(videos),
        "total_hours": round(sum(float(v.get("duration_seconds") or 0) for v in videos) / 3600, 1),
        "first_detected_range": [dates[0], dates[-1]] if dates else [],
        "videos_with_saved_transcripts": sum(1 for v in videos if lib.transcript_files(v["id"])),
        "channels": dict(sorted(channels.items(), key=lambda kv: (-kv[1], kv[0]))),
        "newest": [brief(v) for v in newest],
    }


def search_videos(lib: Library, query: str, channel: str | None = None,
                  detected_since: str | None = None, limit: int = 10) -> dict:
    ranked = []
    for item in filtered(lib.videos(), channel, detected_since, None):
        points, field, text = score(item, query)
        if points:
            ranked.append((points, item, field, text))
    ranked.sort(key=lambda r: (-r[0], r[1].get("first_detected_at", "")))
    return {
        "query": query,
        "match_count": len(ranked),
        "results": [
            {**brief(item), "score": round(points, 1), "matched_in": field, "snippet": text,
             "quick_takeaways": takeaways(item)[:3]}
            for points, item, field, text in ranked[:max(1, min(limit, 50))]
        ],
    }


def list_videos(lib: Library, channel: str | None = None, detected_since: str | None = None,
                detected_before: str | None = None, sort: str = "newest", limit: int = 25,
                offset: int = 0) -> dict:
    items = filtered(lib.videos(), channel, detected_since, detected_before)
    if sort == "longest":
        items.sort(key=lambda v: float(v.get("duration_seconds") or 0), reverse=True)
    else:
        items.sort(key=lambda v: v.get("first_detected_at", ""), reverse=sort != "oldest")
    limit = max(1, min(limit, 100))
    return {
        "total": len(items),
        "offset": offset,
        "videos": [brief(v) for v in items[offset:offset + limit]],
        "next_offset": offset + limit if offset + limit < len(items) else None,
    }


def get_video(lib: Library, video: str, include_description: bool = False) -> dict:
    item = lib.find(video)
    result = {
        **brief(item),
        "upload_date": item.get("upload_date", ""),
        "quick_takeaways": as_list(item.get("quick_takeaways")),
        "summary": clean_executive_summary(str(item.get("summary", ""))),
        "why_valuable": item.get("why_valuable", ""),
        "key_takeaways": as_list(item.get("key_takeaways")),
        "chapters": [
            {"timestamp": c.get("timestamp") or seconds_label(float(c.get("start_seconds", 0))),
             "title": c.get("title", ""), "description": c.get("description", ""),
             "link": jump_url(item, float(c.get("start_seconds", 0)))}
            for c in as_list(item.get("chapters"))
        ],
        "transcript_available": bool(lib.transcript_files(item["id"])),
    }
    if include_description:
        result["creator_description"] = item.get("description", "")
    return result


def get_transcript(lib: Library, video: str, start: str | None = None, end: str | None = None,
                   max_chars: int = 40000) -> dict:
    item = lib.find(video)
    files = lib.transcript_files(item["id"])
    if not files:
        return {**brief(item), "available": False,
                "message": "No transcript is saved for this video; use get_video for its summary and chapters."}
    lines = transcript_lines(files[0], lib.read_transcript(files[0]))
    begin = parse_clock(start) if start else 0.0
    stop = parse_clock(end) if end else float("inf")
    out, used, next_start = [], 0, None
    for seconds, text in lines:
        if seconds < begin or seconds >= stop or not text:
            continue
        line = f"[{seconds_label(seconds)}] {text}"
        if used + len(line) > max(2000, min(max_chars, 150000)):
            next_start = seconds_label(seconds)
            break
        out.append(line)
        used += len(line) + 1
    return {
        **brief(item),
        "available": True,
        "source_file": files[0],
        "text": "\n".join(out),
        "truncated": next_start is not None,
        "continue_from": next_start,
    }


def get_takeaways(lib: Library, video_ids: list[str] | None = None, channel: str | None = None,
                  detected_since: str | None = None, limit: int = 40) -> dict:
    if video_ids:
        items = [lib.find(v) for v in video_ids]
    else:
        items = sorted(filtered(lib.videos(), channel, detected_since, None),
                       key=lambda v: v.get("first_detected_at", ""), reverse=True)
    limit = max(1, min(limit, 150))
    return {
        "total": len(items),
        "videos": [{**brief(v), "takeaways": takeaways(v)} for v in items[:limit]],
        "omitted": max(0, len(items) - limit),
    }


INSTRUCTIONS = """\
VidBot is a personal library of transcript-grounded YouTube video summaries (mostly AI tools, \
agents, automation and creator workflows). Start with library_overview or search_videos, \
use get_takeaways to scan many videos at once, get_video for one video's full summary and \
chapter jump links, and get_transcript only when the summary lacks the detail needed. \
Summaries are model-written from transcripts: attribute prices, benchmarks and claims to the \
creator, and distinguish demonstrated results from claims. Cite videos by title with their link."""


def build_server(lib: Library):
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    server = MCPServer("vidbot-library", instructions=INSTRUCTIONS)
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    def run(fn, *args):
        # Unknown videos and unreachable sources are expected; let Claude see why.
        try:
            return fn(lib, *args)
        except (ValueError, OSError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="library_overview", annotations=read_only)
    def overview() -> dict:
        """Library size, date range, channels and the ten newest videos."""
        return run(library_overview)

    @server.tool(name="search_videos", annotations=read_only)
    def search(query: str, channel: str | None = None, detected_since: str | None = None,
               limit: int = 10) -> dict:
        """Keyword search over titles, takeaways, summaries and chapters, best matches first.

        channel filters by a case-insensitive substring; detected_since is YYYY-MM-DD.
        """
        return run(search_videos, query, channel, detected_since, limit)

    @server.tool(name="list_videos", annotations=read_only)
    def listing(channel: str | None = None, detected_since: str | None = None,
                detected_before: str | None = None, sort: str = "newest", limit: int = 25,
                offset: int = 0) -> dict:
        """Page through videos. sort is newest, oldest or longest; dates are YYYY-MM-DD."""
        return run(list_videos, channel, detected_since, detected_before, sort, limit, offset)

    @server.tool(name="get_video", annotations=read_only)
    def video(video: str, include_description: bool = False) -> dict:
        """Full summary, takeaways and chapters (with jump links) for a video id, URL or unique title."""
        return run(get_video, video, include_description)

    @server.tool(name="get_transcript", annotations=read_only)
    def transcript(video: str, start: str | None = None, end: str | None = None,
                   max_chars: int = 40000) -> dict:
        """Timestamped transcript text, when one is saved. start/end are MM:SS or H:MM:SS.

        Long transcripts are returned in pages; call again with start=continue_from.
        """
        return run(get_transcript, video, start, end, max_chars)

    @server.tool(name="get_takeaways", annotations=read_only)
    def bulk(video_ids: list[str] | None = None, channel: str | None = None,
             detected_since: str | None = None, limit: int = 40) -> dict:
        """The short takeaways of many videos at once, newest first, for cross-video synthesis."""
        return run(get_takeaways, video_ids, channel, detected_since, limit)

    @server.prompt(name="best_of")
    def best_of(since: str = "", focus: str = "") -> str:
        """Pull the most valuable, actionable ideas out of the library."""
        scope = f"videos first detected since {since}" if since else "the whole library"
        angle = f" Focus on: {focus}." if focus else ""
        return (
            f"Using the VidBot tools, review {scope} with get_takeaways, then open the most promising "
            f"videos with get_video.{angle} Give me: (1) the ten most valuable, actionable insights, each "
            "with the video title and chapter link it came from; (2) tools or services worth trying, with "
            "any reported prices; (3) where creators agree or contradict each other; (4) which two or three "
            "videos are worth watching in full and which parts I can skip. Attribute claims to creators."
        )

    @server.prompt(name="deep_dive")
    def deep_dive(video: str) -> str:
        """Turn one video into notes and next actions."""
        return (
            f"Use get_video for {video!r}, and get_transcript for any part where the summary is thin. "
            "Write concise study notes: the core argument, the exact steps or settings shown, the numbers "
            "quoted (attributed), what was demonstrated versus only claimed, and a short checklist of what "
            "I could try this week. Link each point to its chapter."
        )

    return server


def main() -> None:
    build_server(Library()).run()


if __name__ == "__main__":
    main()
