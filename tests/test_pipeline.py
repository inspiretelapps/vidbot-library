import importlib.util
import json
import re
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
            summary = [{"id":"abcdefghijk","title":"A","summary":"S","why_valuable":"V","chapters":[{"start_seconds":0,"title":"Intro","description":detail,"source":"generated"}]}]
            source = root / "summary.json"; source.write_text(json.dumps(summary))
            merge_mod.merge(source, root)
            state = json.loads((root / "data/state.json").read_text())
            self.assertIn("abcdefghijk", state["seen"])
            self.assertEqual(1, len(json.loads((root / "data/videos.json").read_text())))
        finally: td.cleanup()

    def test_rejects_empty_chapters(self):
        td, root = self.fixture()
        try:
            source = root / "summary.json"; source.write_text(json.dumps({"id":"abcdefghijk","title":"A","summary":"S","why_valuable":"V","chapters":[]}))
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

    def test_site_offers_local_archive_workflow(self):
        html = (ROOT / "site/index.html").read_text()
        self.assertIn("YouSummary", html)
        self.assertNotIn("View Summary", html)
        self.assertIn("yousummary-archived", html)
        self.assertIn("data-view=\"archive\"", html)
        self.assertIn("type=\"checkbox\"", html)
        self.assertNotIn("Watch on YouTube", html)

    def test_library_chapters_are_detailed(self):
        videos = json.loads((ROOT / "data/videos.json").read_text())
        chapters = [chapter for video in videos for chapter in video["chapters"]]
        self.assertGreater(len(chapters), 0)
        for chapter in chapters:
            self.assertGreaterEqual(len(chapter["description"]), 180)
            self.assertGreaterEqual(len(re.findall(r"[.!?](?:\s|$)", chapter["description"])), 2)

if __name__ == "__main__": unittest.main()
