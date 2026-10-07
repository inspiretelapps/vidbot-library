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
render_mod = module("scripts.render_site", ROOT / "scripts/render_site.py")
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
            summary = [{"id":"abcdefghijk","title":"A","description":"Full creator description with https://example.test/resource","summary":"A useful account of the workflow and its practical limits.","why_valuable":"The comparison exposes a concrete tradeoff between speed and reliability.","key_takeaways":["The demonstrated workflow is fast but needs verification."],"chapters":[{"start_seconds":0,"title":"Intro","description":detail,"source":"generated"}]}]
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

    def test_merge_keeps_quick_points_and_long_summary(self):
        td, root = self.fixture()
        try:
            item = json.loads((ROOT / "data/videos.json").read_text())[0]
            item["quick_takeaways"] = [
                "Use a context display to track remaining capacity and choose when to compact.",
                "Review a mod's file and network access before installing it.",
            ]
            source = root / "summary.json"
            source.write_text(json.dumps(item))
            merge_mod.merge(source, root)
            render_mod.render(root)
            published = json.loads((root / "public/videos.json").read_text())["videos"][0]
            self.assertEqual(item["quick_takeaways"], published["quick_takeaways"])
            self.assertEqual(merge_mod.clean_executive_summary(item["summary"]), published["summary"])
            self.assertEqual(item["key_takeaways"], published["key_takeaways"])
            self.assertEqual(item["chapters"], published["chapters"])
        finally: td.cleanup()

    def test_rejects_unusable_one_minute_points(self):
        item = json.loads((ROOT / "data/videos.json").read_text())[0]
        invalid_points = [
            "A single string instead of a list",
            [],
            [None],
            ["   "],
            ["Review the mod.", " review  the MOD. "],
            ["word " * 201],
            [f"Distinct point {i}." for i in range(7)],
        ]
        for points in invalid_points:
            with self.subTest(points=points):
                item["quick_takeaways"] = points
                with self.assertRaisesRegex(ValueError, "quick takeaways"):
                    merge_mod.validate(item)

    def test_merge_removes_video_timestamps_only_from_executive_summary(self):
        td, root = self.fixture()
        try:
            item = json.loads((ROOT / "data/videos.json").read_text())[0]
            item["summary"] = "Recommendation [00:00–03:18]: Review permissions.\n\n[03:18–05:34 | Keep control] Schedule a 10:00 a.m. check; John 3:16 is a scripture citation."
            chapters = item["chapters"]
            source = root / "summary.json"
            source.write_text(json.dumps(item))
            merge_mod.merge(source, root)
            render_mod.render(root)
            published = json.loads((root / "public/videos.json").read_text())["videos"][0]
            self.assertEqual("Recommendation: Review permissions.\n\nKeep control: Schedule a 10:00 a.m. check; John 3:16 is a scripture citation.", published["summary"])
            self.assertEqual(chapters, published["chapters"])
        finally: td.cleanup()

    def summary_cleanup_examples(self):
        return {
            "**00:00–06:30 | Demand first.** Validate the product.": "**Demand first.** Validate the product.",
            "00:00–04:22 | Design: Compare the results.": "Design: Compare the results.",
            "[09:45–11:15; 14:15–16:57 | Billing] Charge for usage.": "Billing: Charge for usage.",
            "(36:51–end) The final verdict.": "The final verdict.",
            "[00:40–03:50] Review the model. (WorkOS sponsor segment: ~02:00–03:20.)": "Review the model. (WorkOS sponsor segment.)",
            "He reports 51.3% at 02:30–02:40 and 77.5% at 04:16–04:26.": "He reports 51.3% and 77.5%.",
            "At 06:09 he explains. A promotion at 07:31 is sponsorship.": "He explains. A promotion is sponsorship.",
            "Meet at 10:00 a.m. and discuss John 3:16.": "Meet at 10:00 a.m. and discuss John 3:16.",
            "Prerequisites — 00:54–06:23: Check the setup.": "Prerequisites: Check the setup.",
            "One point of contact — 00:20: Delegate tasks.": "One point of contact: Delegate tasks.",
            "Identity — 25:02–01:15:14: Accept help.": "Identity: Accept help.",
            "**Verdict — 17:26–end:** Review the output.": "**Verdict:** Review the output.",
            "Setup - 00:54-06:23: Check permissions.\n\nReview – 06:24: Check the result.": "Setup: Check permissions.\n\nReview: Check the result.",
            "The exercise arrives at 01:02: break the job into tasks.": "The exercise arrives: break the job into tasks.",
            "00:54–06:23: Check the setup.": "Check the setup.",
            "At 10:00 a.m. check John 3:16. Office hours — 10:00 a.m.": "At 10:00 a.m. check John 3:16. Office hours — 10:00 a.m.",
        }

    def test_summary_cleanup_handles_existing_annotation_formats(self):
        examples = self.summary_cleanup_examples()
        for original, expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(expected, merge_mod.clean_executive_summary(original))
                self.assertEqual(expected, merge_mod.clean_executive_summary(expected))

    def test_render_cleans_summaries_that_bypass_import(self):
        td, root = self.fixture()
        try:
            item = json.loads((ROOT / "data/videos.json").read_text())[0]
            item["summary"] = "Prerequisites — 00:54–06:23: Check the setup.\n\nConclusion — 01:15:14–01:40:18: Review the result."
            canonical = json.dumps([item])
            (root / "data/videos.json").write_text(canonical)
            render_mod.render(root)
            published = json.loads((root / "public/videos.json").read_text())["videos"][0]
            self.assertEqual("Prerequisites: Check the setup.\n\nConclusion: Review the result.", published["summary"])
            self.assertEqual(item["chapters"], published["chapters"])
            self.assertEqual(canonical, (root / "data/videos.json").read_text())
        finally: td.cleanup()

    def test_browser_cleans_raw_summaries_consistently_with_importer(self):
        html = (ROOT / "site/index.html").read_text()
        helper = re.search(r"function cleanExecutiveSummary\(summary\)\{.*?\n    \}", html, re.DOTALL)
        self.assertIsNotNone(helper)
        self.assertIn("${cleanExecutiveSummary(v.summary).split", html)
        examples = self.summary_cleanup_examples()
        videos = json.loads((ROOT / "data/videos.json").read_text())
        originals = list(examples) + [v["summary"] for v in videos]
        expected = list(examples.values()) + [merge_mod.clean_executive_summary(v["summary"]) for v in videos]
        script = helper.group(0) + "\nconsole.log(JSON.stringify(" + json.dumps(originals) + ".map(cleanExecutiveSummary)))"
        result = subprocess.run(["node"], input=script, capture_output=True, text=True, check=True)
        self.assertEqual(expected, json.loads(result.stdout))

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

    def test_rejects_caption_stitching_as_executive_summary(self):
        item = {"id":"abcdefghijk", "title":"A", "description":"Creator description",
                "summary":"The video explains a sentence copied from captions. It later expands the case with another caption sentence, connecting the example to the presenter’s broader conclusion.",
                "why_valuable":"A concrete comparison of two approaches with practical tradeoffs.",
                "key_takeaways":["The second approach costs less but needs more time."],
                "chapters":[{"start_seconds":0,"title":"Specific chapter","source":"generated",
                             "description":"The presenter tests both approaches on a real project and identifies a concrete failure in the first. The second succeeds, although it takes longer and is less suitable for a quick iteration."}]}
        with self.assertRaisesRegex(ValueError, "executive summary"):
            merge_mod.validate(item, quality=True)

    def test_rejects_generic_value_and_chapter_titles_as_takeaways(self):
        item = {"id":"abcdefghijk", "title":"A", "description":"Creator description",
                "summary":"The presenter compares approaches on a real project, finding that the second produces a stronger result despite a longer runtime. The comparison is limited to one trial and should not be treated as a universal ranking.",
                "why_valuable":"It provides a caption-grounded walkthrough of A, with the creator’s full description and navigable intervals retained for verification.",
                "key_takeaways":["Part 1","Part 2"],
                "chapters":[{"start_seconds":0,"title":"Specific chapter","source":"generated",
                             "description":"The presenter tests both approaches on a real project and identifies a concrete failure in the first. The second succeeds, although it takes longer and is less suitable for a quick iteration."}]}
        with self.assertRaisesRegex(ValueError, "value statement"):
            merge_mod.validate(item, quality=True)
        item["why_valuable"] = "A useful comparison of actual project results and the tradeoff between output quality and runtime."
        with self.assertRaisesRegex(ValueError, "takeaways"):
            merge_mod.validate(item, quality=True)

    def test_all_published_chapters_pass_summary_validation(self):
        videos = json.loads((ROOT / "data/videos.json").read_text())
        for video in videos:
            with self.subTest(video=video["id"]):
                merge_mod.validate(video)

    def test_library_chapters_are_detailed(self):
        videos = json.loads((ROOT / "data/videos.json").read_text())
        chapters = [chapter for video in videos for chapter in video["chapters"]]
        self.assertGreater(len(chapters), 0)
        for chapter in chapters:
            self.assertGreaterEqual(len(chapter["description"]), 180)
            self.assertGreaterEqual(len(re.findall(r"[.!?](?:\s|$)", chapter["description"])), 2)

if __name__ == "__main__": unittest.main()
