import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

mcp_mod = module("scripts.mcp_server", ROOT / "scripts/mcp_server.py")

VIDEOS = [
    {"id": "abcdefghijk", "title": "Resolve MCP rough cuts", "channel": "Editor Channel", "duration_seconds": "600",
     "first_detected_at": "2026-10-20T06:00:00+02:00", "url": "https://www.youtube.com/watch?v=abcdefghijk",
     "summary": "Rough cuts — 00:54–06:23\nResolve keeps the intended takes.",
     "quick_takeaways": ["Resolve MCP made a usable rough cut."], "key_takeaways": ["01:10 — Same footage, three tools."],
     "chapters": [{"start_seconds": 75, "timestamp": "01:15", "title": "Test", "description": "The comparison."}]},
    {"id": "lmnopqrstuv", "title": "Agent pricing explained", "channel": "Other", "duration_seconds": "3700",
     "first_detected_at": "2026-09-20T06:00:00+02:00", "summary": "Costs of hosted agents.",
     "key_takeaways": ["Hosted agents cost more than local ones."], "chapters": []},
]

class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        (root / "data/transcripts").mkdir(parents=True)
        (root / "data/videos.json").write_text(json.dumps(VIDEOS))
        (root / "data/transcripts/abcdefghijk.captions.json").write_text(json.dumps(
            {"events": [{"tStartMs": 0, "segs": [{"utf8": "Hello"}]}, {"tStartMs": 65000, "segs": [{"utf8": "Second"}, {"utf8": " part"}]}]}))
        (root / "data/transcripts/lmnopqrstuv.transcript.txt").write_text("00:00 First line\n1:01:05 Late line\n")
        self.lib = mcp_mod.Library(root, "https://unused.test")

    def tearDown(self):
        self.td.cleanup()

    def test_search_ranks_title_matches_and_filters(self):
        result = mcp_mod.search_videos(self.lib, "resolve rough cut")
        self.assertEqual(result["results"][0]["id"], "abcdefghijk")
        self.assertEqual(mcp_mod.search_videos(self.lib, "agents", channel="editor")["match_count"], 0)
        self.assertEqual(mcp_mod.search_videos(self.lib, "agents", detected_since="2026-10-01")["match_count"], 0)

    def test_get_video_accepts_urls_and_links_chapters(self):
        video = mcp_mod.get_video(self.lib, "https://youtu.be/abcdefghijk")
        self.assertEqual(video["chapters"][0]["link"], "https://www.youtube.com/watch?v=abcdefghijk&t=75s")
        self.assertNotIn("00:54", video["summary"])
        self.assertTrue(video["transcript_available"])
        with self.assertRaises(ValueError):
            mcp_mod.get_video(self.lib, "zzzzzzzzzzz")

    def test_transcripts_normalise_formats_and_page(self):
        caption = mcp_mod.get_transcript(self.lib, "abcdefghijk", start="01:00")
        self.assertEqual(caption["text"], "[01:05] Second part")
        text = mcp_mod.get_transcript(self.lib, "lmnopqrstuv")
        self.assertEqual(text["text"].splitlines()[-1], "[1:01:05] Late line")
        long_lines = "\n".join(f"{m:02d}:00 {'word ' * 100}" for m in range(60))
        (Path(self.td.name) / "data/transcripts/lmnopqrstuv.transcript.txt").write_text(long_lines)
        paged = mcp_mod.get_transcript(self.lib, "lmnopqrstuv", max_chars=2000)
        self.assertTrue(paged["truncated"])
        self.assertEqual(paged["continue_from"], "03:00")

    def test_takeaways_fall_back_to_key_takeaways(self):
        result = mcp_mod.get_takeaways(self.lib)
        self.assertEqual([v["id"] for v in result["videos"]], ["abcdefghijk", "lmnopqrstuv"])
        self.assertEqual(result["videos"][1]["takeaways"], ["Hosted agents cost more than local ones."])

    def test_overview_and_listing(self):
        overview = mcp_mod.library_overview(self.lib)
        self.assertEqual(overview["video_count"], 2)
        self.assertEqual(overview["videos_with_saved_transcripts"], 2)
        listing = mcp_mod.list_videos(self.lib, sort="longest", limit=1)
        self.assertEqual(listing["videos"][0]["id"], "lmnopqrstuv")
        self.assertEqual(listing["next_offset"], 1)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp package not installed")
    def test_server_registers_read_only_tools(self):
        import asyncio
        server = mcp_mod.build_server(self.lib)
        tools = asyncio.run(server.list_tools())
        self.assertEqual({t.name for t in tools}, {"library_overview", "search_videos", "list_videos",
                                                   "get_video", "get_transcript", "get_takeaways"})
        self.assertTrue(all(t.annotations.read_only_hint for t in tools))

if __name__ == "__main__":
    unittest.main()
