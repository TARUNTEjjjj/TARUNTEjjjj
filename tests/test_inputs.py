"""Hand-edited inputs are checked before any card is written.

profile.json, scripts/icons.json and the stats snapshot behind a --data preview are all
written by hand, so a slip in one of them must stop the build with a message that names it,
never publish a quietly different card.
"""

import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build
import cards
from svg import THEMES

SAMPLE = ROOT / "scripts" / "sample-stats.json"
LOGO = {"title": "Thing", "hex": "F03C2E", "path": "M2 2h20v20H2zM7 7v10h10V7z"}  # a complete icons.json entry
PROFILE = {"name": "Example", "typing": ["Hello"], "stack": [{"group": "Tools", "items": ["thing"]}]}


def run_build(*args) -> None:
    """build.main as on a maintainer's machine (not GitHub Actions), without its progress lines."""
    with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
        build.main([str(arg) for arg in args])


class DuplicateKeyTests(unittest.TestCase):
    """json keeps only the last of two equal keys, which would silently drop the earlier one."""

    def refusal(self, profile: str) -> str:
        """Why a build with this profile.json stopped; also checks that it wrote nothing."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "profile.json").write_text(profile, encoding="utf-8")
            with patch.object(build, "ROOT", root), self.assertRaises(SystemExit) as stopped:
                run_build("--output-dir", root / "out")
            self.assertFalse((root / "out").exists())
        return str(stopped.exception)

    def test_repeated_profile_key_stops_the_build(self):
        # Without the check, the first stack (two logos) is dropped and a one-logo card is published.
        message = self.refusal('{"name": "Example", "typing": ["Hello"],'
                               ' "stack": [{"group": "Tools", "items": ["git", "github"]}],'
                               ' "stack": [{"group": "Cloud", "items": ["github"]}]}')
        self.assertEqual(message, "profile.json: duplicate key stack; merge them into one.")

    def test_repeated_nested_profile_key_stops_the_build(self):
        message = self.refusal('{"name": "Example", "typing": ["Hello"],'
                               ' "languages": {"hide": ["CSS"], "exclude_repos": ["example"], "hide": []}}')
        self.assertEqual(message, "profile.json: duplicate key hide; merge them into one.")

    def test_profile_without_repeats_builds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "profile.json").write_text('{"name": "Example", "typing": ["Hello"]}', encoding="utf-8")
            with patch.object(build, "ROOT", root):
                run_build("--output-dir", root / "out")
            self.assertEqual(len(list((root / "out").glob("*.svg"))), 4)

    def test_repeated_logo_is_still_refused_with_its_own_advice(self):
        with tempfile.TemporaryDirectory() as temporary:
            icons = Path(temporary) / "icons.json"
            icons.write_text('{"brands": {"git": {}, "git": {}}, "octicons": {}}', encoding="utf-8")
            with self.assertRaises(SystemExit) as stopped:
                build.load_icons(icons)
        self.assertEqual(str(stopped.exception), "icons.json: duplicate key git; keep one entry per logo.")


class LogoPathTests(unittest.TestCase):
    """An icons.json path goes into d="..." of the tech stack card, so it must be path data only."""

    def test_anything_but_path_data_is_refused(self):
        paths = {
            "copied closing tag": LOGO["path"] + "</svg>",
            "markup after a quote": 'M0 0h24"/><text x="0" y="20" font-size="40">INJECTED</text><path d="M0 0',
            "whole svg element": f'<svg role="img" viewBox="0 0 24 24"><path d="{LOGO["path"]}"/></svg>',
            "stray end of tag": LOGO["path"] + '"/>',
            "empty": "",
            "blank": "  ",
            "null": None,
        }
        for name, path in paths.items():
            with self.subTest(path=name):
                with self.assertRaises(SystemExit) as stopped:
                    build.brand_for("thing", "Thing", {**LOGO, "path": path})
                self.assertIn("scripts/icons.json: thing path must be SVG path data only", str(stopped.exception))

    def test_every_committed_logo_is_accepted(self):
        for slug, data in build.load_icons()["brands"].items():
            with self.subTest(logo=slug):
                brand = build.brand_for(slug, data["title"], data)
                self.assertTrue(brand.path or brand.art)

    def test_bad_path_stops_the_build_before_anything_is_written(self):
        icons = {"brands": {"thing": {**LOGO, "path": LOGO["path"] + "</svg>"}}, "octicons": {}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
            with patch.object(build, "ROOT", root), patch.object(build, "load_icons", return_value=icons):
                with self.assertRaises(SystemExit) as stopped:
                    run_build("--output-dir", root / "out")
            self.assertFalse((root / "out").exists())
        self.assertIn("thing path must be SVG path data only", str(stopped.exception))

    def test_renderers_escape_path_data(self):
        # Well-formed, so the SVG check in build.main alone would let it through.
        hostile = 'M0 0"/><text>INJECTED</text><path d="M0 0'
        pill = cards._pill(0, 0, cards.Brand("Thing", LOGO["hex"], hostile), THEMES[0])
        icon = cards._icon([hostile], 0, 0, "#000000")
        for markup in (pill, icon):
            self.assertNotIn("<text>INJECTED", markup)
            self.assertIn('d="M0 0&quot;/&gt;&lt;text&gt;INJECTED', markup)


class ShapelessLogoTests(unittest.TestCase):
    """A logo with nothing to draw becomes a letter tile, but never without saying so."""

    def stack_with(self, entry):
        """(warnings, brand) for a one-logo stack whose icons.json entry is `entry` (None: no entry)."""
        icons = {"brands": {} if entry is None else {"thing": entry}}
        with patch.object(build, "warn") as warn:
            groups = build.stack_groups(PROFILE, icons)
        return [call.args[0] for call in warn.call_args_list], groups[0][1][0]

    def test_entry_without_path_or_art_warns_once(self):
        entries = {
            "no entry": None,
            "metadata only": {"title": "Thing", "hex": "F03C2E", "source": "https://example.com", "license": "CC0"},
            "misspelt key": {"title": "Thing", "hex": "F03C2E", "paths": LOGO["path"]},
            "title only": {"title": "Thing"},
        }
        for name, entry in entries.items():
            with self.subTest(entry=name):
                warnings, brand = self.stack_with(entry)
                self.assertEqual(len(warnings), 1)
                self.assertIn("so it is drawn as a letter tile", warnings[0])
                self.assertEqual((brand.path, brand.art), (None, None))

    def test_complete_entry_does_not_warn(self):
        warnings, brand = self.stack_with(LOGO)
        self.assertEqual(warnings, [])
        self.assertEqual(brand.path, LOGO["path"])

    def test_unusable_shape_stops_the_build(self):
        art = {"viewBox": "0 0 1 1", "body": "<path d='M0 0h1v1z'/>"}
        entries = {
            "art null": {"title": "Thing", "art": None},
            "art null on an entry with a path": {**LOGO, "art": None},
            "art null beside art_dark": {"title": "Thing", "art": None, "art_dark": art},
            "art without a body": {"title": "Thing", "art": {}},
            "path without a hex": {"title": "Thing", "path": LOGO["path"]},
        }
        for name, entry in entries.items():
            with self.subTest(entry=name), self.assertRaises(SystemExit):
                build.brand_for("thing", "Thing", entry)

    def test_art_dark_stays_optional(self):
        art = {"viewBox": "0 0 1 1", "body": "<path d='M0 0h1v1z'/>"}
        for entry in ({"title": "Thing", "art": art}, {"title": "Thing", "art": art, "art_dark": None}):
            self.assertEqual(build.brand_for("thing", "Thing", entry).art, art)


class SnapshotTests(unittest.TestCase):
    """The documented activity preview has a snapshot to read: scripts/sample-stats.json."""

    def preview(self, *args) -> str:
        """The dark activity card that a --data preview of the sample writes."""
        with tempfile.TemporaryDirectory() as temporary:
            run_build("--data", SAMPLE, "--output-dir", temporary, *args)
            self.assertEqual(len(list(Path(temporary).glob("*.svg"))), 6)
            return (Path(temporary) / "activity-dark.svg").read_text(encoding="utf-8")

    def test_sample_preview_is_drawn_as_of_its_last_day(self):
        # Counted from today's date instead, the sample's six-day streak would read "no active streak".
        card = self.preview()
        self.assertIn("updated 9 Nov 2026", card)
        self.assertIn("current streak 6 days", card)

    def test_duplicate_snapshot_keys_are_refused_without_writing(self):
        sample = SAMPLE.read_text(encoding="utf-8")
        cases = {
            "followers": sample.rstrip()[:-1] + ', "followers": 99999}',
            "2026-11-09": sample.replace('"days": {', '"days": {"2026-11-09": 99999,'),
        }
        for key, source in cases.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                snapshot, out = Path(temporary) / "snapshot.json", Path(temporary) / "out"
                snapshot.write_text(source, encoding="utf-8")
                with self.assertRaises(SystemExit) as stopped:
                    run_build("--data", snapshot, "--output-dir", out)
                self.assertIn(f"snapshot.json: duplicate key {key};", str(stopped.exception))
                self.assertFalse(out.exists())

    def test_today_overrides_the_snapshot_day(self):
        card = self.preview("--today", "2026-10-18")
        self.assertIn("updated 18 Oct 2026", card)
        self.assertIn("36 contributions", card)
        self.assertIn("current streak 9 days", card)

    def test_snapshot_without_a_key_is_named_and_nothing_is_written(self):
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        for key in ("days", "publicRepos", "repos", "login"):
            with self.subTest(missing=key), tempfile.TemporaryDirectory() as temporary:
                snapshot, out = Path(temporary) / "snapshot.json", Path(temporary) / "out"
                snapshot.write_text(json.dumps({k: v for k, v in sample.items() if k != key}), encoding="utf-8")
                with self.assertRaises(SystemExit) as stopped:
                    run_build("--data", snapshot, "--output-dir", out)
                self.assertIn(f"no '{key}' key; scripts/sample-stats.json shows the format.", str(stopped.exception))
                self.assertFalse(out.exists())

    def test_days_key_that_is_not_a_date_is_named_and_nothing_is_written(self):
        # Every days key is read as a date, zero counts too, and the last one is the default day:
        # a hand-written "2026-11-9" must stop the preview with its name, not with a bare ValueError.
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        advice = "is not a YYYY-MM-DD date; scripts/sample-stats.json shows the format."
        for key in ("2026-11-9", "9 Nov 2026", "2026-02-30"):
            for today in ((), ("--today", "2026-11-09")):
                with self.subTest(key=key, today=today), tempfile.TemporaryDirectory() as temporary:
                    snapshot, out = Path(temporary) / "snapshot.json", Path(temporary) / "out"
                    snapshot.write_text(json.dumps({**sample, "days": {**sample["days"], key: 0}}), encoding="utf-8")
                    with self.assertRaises(SystemExit) as stopped:
                        run_build("--data", snapshot, "--output-dir", out, *today)
                    self.assertEqual(str(stopped.exception), f"{snapshot}: days key {key!r} {advice}")
                    self.assertFalse(out.exists())

    def test_missing_snapshot_file_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "out"
            with self.assertRaises(FileNotFoundError):
                run_build("--data", Path(temporary) / "missing.json", "--output-dir", out)
            self.assertFalse(out.exists())

    def test_snapshot_with_no_days_is_drawn_as_of_today(self):
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        sample["days"] = {}  # no last day to go by
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "snapshot.json"
            snapshot.write_text(json.dumps(sample), encoding="utf-8")
            before = datetime.now(timezone.utc).date()
            summary = build.snapshot_summary(snapshot, {}, None)
        self.assertIn(summary.today, (before, datetime.now(timezone.utc).date()))
        self.assertEqual(summary.contributions, 0)

    def test_snapshot_from_before_private_counts_still_loads(self):
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        del sample["privateContributions"]
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "snapshot.json"
            snapshot.write_text(json.dumps(sample), encoding="utf-8")
            run_build("--data", snapshot, "--check")

    def test_every_documented_snapshot_exists(self):
        documents = {name: (ROOT / name).read_text(encoding="utf-8") for name in ("scripts/build.py", "README.md")}
        named = {(name, path) for name, text in documents.items() for path in re.findall(r"--data (\S+\.json)", text)}
        self.assertIn("scripts/build.py", {name for name, _ in named})  # its usage text names one
        for name, path in sorted(named):
            self.assertTrue((ROOT / path).is_file(), f"{name} documents --data {path}, which does not exist")


if __name__ == "__main__":
    unittest.main()
