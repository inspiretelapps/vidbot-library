import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

merge_mod = module("merge_summary", ROOT / "scripts/merge_summary.py")
render_mod = module("render_site", ROOT / "scripts/render_site.py")
manual_refresh_mod = module("manual_refresh_server", ROOT / "scripts/manual_refresh_server.py")

class PipelineTests(unittest.TestCase):
    def fixture(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "data").mkdir(); (root / "site").mkdir()
        (root / "config.json").write_text(json.dumps({"playlist_title":"Test","playlist_url":"https://example.test","timezone":"Africa/Johannesburg","scan_times":["06:00"]}))
        (root / "data/videos.json").write_text("[]")
        (root / "data/state.json").write_text('{"seen":{}}')
        (root / "site/index.html").write_text("<!doctype html><title>Test</title>")
        return td, root

    def test_merge_marks_seen_only_after_valid_summary(self):
        td, root = self.fixture()
        try:
            detail = "This chapter explains the central idea with enough context to understand what the speaker is demonstrating. It also identifies the practical lesson and why that part of the discussion matters to the viewer."
            summary = [{"id":"abcdefghijk","title":"A","description":"Full creator description with https://example.test/resource","summary":"S","why_valuable":"V","chapters":[{"start_seconds":0,"title":"Intro","description":detail,"source":"generated"}]}]
            source = root / "summary.json"; source.write_text(json.dumps(summary))
            merge_mod.merge(source, root)
            state = json.loads((root / "data/state.json").read_text())
            self.assertIn("abcdefghijk", state["seen"])
            self.assertEqual(1, len(json.loads((root / "data/videos.json").read_text())))
        finally: td.cleanup()

    def test_rejects_empty_chapters(self):
        td, root = self.fixture()
        try:
            source = root / "summary.json"; source.write_text(json.dumps({"id":"abcdefghijk","title":"A","description":"Full creator description","summary":"S","why_valuable":"V","chapters":[]}))
            with self.assertRaises(ValueError): merge_mod.merge(source, root)
        finally: td.cleanup()

    def test_render_writes_payload(self):
        td, root = self.fixture()
        try:
            result = render_mod.render(root)
            self.assertEqual(0, result["video_count"])
            payload = json.loads((root / "public/videos.json").read_text())
            self.assertEqual("Test", payload["playlist"]["title"])
        finally: td.cleanup()

    def test_site_formats_every_library_upload_date(self):
        html = (ROOT / "site/index.html").read_text()
        match = re.search(r"const fmtDate=.*?;(?=\n)", html)
        self.assertIsNotNone(match)
        fmt = match.group(0) if match else ""
        dates = [video.get("upload_date") for video in json.loads((ROOT / "data/videos.json").read_text())]
        script = fmt + "\nconsole.log(JSON.stringify(" + json.dumps(dates) + ".map(fmtDate)))"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        formatted = json.loads(result.stdout)
        self.assertEqual(len(dates), len(formatted))
        self.assertTrue(all("Invalid" not in date for date in formatted))

    def test_site_offers_local_archive_workflow(self):
        html = (ROOT / "site/index.html").read_text()
        self.assertIn("YouSummary", html)
        self.assertNotIn("View Summary", html)
        self.assertIn("yousummary-archived", html)
        self.assertIn("data-view=\"archive\"", html)
        self.assertIn('class="archive-icon"', html)
        self.assertIn("Archive this video", html)
        self.assertIn('class="video-expand-toggle"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('class="video-content" hidden', html)
        self.assertNotIn("Archive after reading", html)
        self.assertNotIn("Watch on YouTube", html)

    def test_site_offers_manual_playlist_refresh(self):
        html = (ROOT / "site/index.html").read_text()
        self.assertIn('id="refreshButton"', html)
        self.assertIn("Run playlist scan now", html)
        self.assertIn("/refresh/bf7abd0a6c618ad43854c54de8dd4a7700b51796edbd65e5", html)

    def test_manual_refresh_rejects_wrong_origin_and_throttles(self):
        gate = manual_refresh_mod.RefreshGate(
            allowed_origin="https://inspiretelapps.github.io",
            cooldown_seconds=900,
        )
        self.assertEqual((False, 403), gate.allow("https://example.com", now=1000))
        self.assertEqual((True, 202), gate.allow("https://inspiretelapps.github.io", now=1000))
        self.assertEqual((False, 429), gate.allow("https://inspiretelapps.github.io", now=1100))
        self.assertEqual((True, 202), gate.allow("https://inspiretelapps.github.io", now=1901))

    def test_library_includes_full_descriptions_and_clickable_links(self):
        videos = json.loads((ROOT / "data/videos.json").read_text())
        self.assertTrue(videos)
        self.assertTrue(all(str(video.get("description", "")).strip() for video in videos))
        example = next(video for video in videos if video["id"] == "9a6oCFbs0O8")
        self.assertIn("https://github.com/NVIDIA/SkillSpector", example["description"])
        html = (ROOT / "site/index.html").read_text()
        self.assertIn("Full video description", html)
        self.assertIn("linkifyDescription", html)

    def test_rejects_missing_full_description(self):
        item = {
            "id": "abcdefghijk",
            "title": "A",
            "summary": "S",
            "why_valuable": "V",
            "chapters": [{
                "start_seconds": 0,
                "title": "Intro",
                "description": "This is a sufficiently detailed chapter sentence that explains the content and practical context clearly. This second sentence makes the chapter description complete and useful for testing.",
                "source": "generated",
            }],
        }
        with self.assertRaisesRegex(ValueError, "description"):
            merge_mod.validate(item)
        item["description"] = ""
        with self.assertRaisesRegex(ValueError, "description"):
            merge_mod.validate(item)

    def test_rejects_title_and_caption_template_chapter(self):
        item = {
            "id": "abcdefghijk", "title": "A", "description": "Creator description", "summary": "S", "why_valuable": "V",
            "chapters": [{
                "start_seconds": 0, "title": "Intro", "source": "generated",
                "description": "This section is titled ‘Intro’ and develops that topic through the speaker’s example or explanation. Caption excerpt: The transcript begins here and has enough extra words to exceed the required length without actually summarising the chapter in a useful way.",
            }],
        }
        with self.assertRaisesRegex(ValueError, "title/caption template"):
            merge_mod.validate(item)

    def test_rejects_placeholder_generated_titles(self):
        item = {
            "id": "abcdefghijk", "title": "A", "description": "Creator description", "summary": "S", "why_valuable": "V",
            "chapters": [{
                "start_seconds": 548, "title": "Discussion at 9:08", "source": "generated",
                "description": "The speaker compares two models on cost and coding ability, citing a concrete pricing change. They then explain why the lower price does not offset the quality gap for demanding work, and how that affects model selection.",
            }],
        }
        with self.assertRaisesRegex(ValueError, "placeholder title"):
            merge_mod.validate(item)
        item["chapters"][0]["title"] = "Part 1"
        with self.assertRaisesRegex(ValueError, "placeholder title"):
            merge_mod.validate(item)

    def test_rejects_caption_filler_even_without_old_opening(self):
        item = {
            "id": "abcdefghijk", "title": "A", "description": "Creator description", "summary": "S", "why_valuable": "V",
            "chapters": [{
                "start_seconds": 0, "title": "Smart Home Demo", "source": "creator",
                "description": "Here the discussion focuses on the speaker's opening words about switching the lights. The middle of the segment adds another caption sentence without explaining the demo or its outcome, and the final sentence makes a generic claim.",
            }],
        }
        with self.assertRaisesRegex(ValueError, "caption template"):
            merge_mod.validate(item)

    def test_library_chapters_are_detailed(self):
        videos = json.loads((ROOT / "data/videos.json").read_text())
        chapters = [chapter for video in videos for chapter in video["chapters"]]
        self.assertGreater(len(chapters), 0)
        for chapter in chapters:
            self.assertGreaterEqual(len(chapter["description"]), 180)
            self.assertGreaterEqual(len(re.findall(r"[.!?](?:\s|$)", chapter["description"])), 2)

if __name__ == "__main__": unittest.main()
