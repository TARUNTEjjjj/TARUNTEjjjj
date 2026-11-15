"""The GitHub activity card: what its numbers count, when it is drawn and where it goes."""

import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build
import cards
import stats
from svg import THEMES

SAMPLE = ROOT / "scripts" / "sample-stats.json"
OCTICONS = build.load_icons()["octicons"]
CARDS = ["header-dark.svg", "header-light.svg", "stack-dark.svg", "stack-light.svg"]
ACTIVITY = ["activity-dark.svg", "activity-light.svg"]
# What a "Build profile" workflow step sees.
WORKFLOW = {"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "token", "GITHUB_REPOSITORY_OWNER": "example"}


class FakeGitHub:
    """Stands in for stats._graphql and answers as GitHub does.

    A languages connection is cut to the `first:` its query asks for and continues from
    `after`, and restrictedContributionsCount comes back only if the query names it.
    """

    def __init__(self, repos=None, days=None, private=None):
        self.repos = repos or {}  # {repository: [(language, bytes), ...]}
        self.days = days or {}  # {"YYYY-MM-DD": contributions}
        self.private = private or {}  # {year: how many of its contributions are in private repositories}
        self.gone = set()  # repositories deleted or made private after the first request
        self.queries = []

    def __call__(self, query: str, variables: dict, token: str) -> dict:
        self.queries.append(query)
        if "contributionsCollection" in query:
            return {"user": self._years(query)}
        first = int(re.search(r"languages\(first: (\d+)", query).group(1))
        if "repository(owner:" in query:
            if variables["name"] in self.gone:
                return {"repository": None}
            return {"repository": {"languages": self._languages(variables["name"], first, variables["cursor"])}}
        nodes = [{"name": name, "stargazerCount": 0, "languages": self._languages(name, first, None)}
                 for name in self.repos]
        return {
            "prs": {"issueCount": 2},
            "issues": {"issueCount": 0},
            "user": {
                "login": variables["login"],
                "createdAt": "2025-07-01T09:30:00Z",
                "followers": {"totalCount": 0},
                "publicRepos": {"totalCount": len(self.repos)},
                "repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes},
            },
        }

    def _languages(self, name: str, first: int, after) -> dict:
        ranked = sorted(self.repos[name], key=lambda language: -language[1])
        start = int(after or 0)
        return {
            "pageInfo": {"hasNextPage": start + first < len(ranked), "endCursor": str(start + first)},
            "edges": [{"size": size, "node": {"name": language, "color": "#3572A5"}}
                      for language, size in ranked[start:start + first]],
        }

    def _years(self, query: str) -> dict:
        years = {}
        for alias, start, end in re.findall(r'(y\d+): contributionsCollection\(from: "([^"]+)", to: "([^"]+)"\)', query):
            days = [{"date": day, "contributionCount": count} for day, count in self.days.items()
                    if start[:10] <= day <= end[:10]]
            years[alias] = {"totalCommitContributions": 0, "contributionCalendar": {"weeks": [{"contributionDays": days}]}}
            if "restrictedContributionsCount" in query:
                years[alias]["restrictedContributionsCount"] = self.private.get(int(alias[1:]), 0)
        return years


def fetch(github: FakeGitHub) -> dict:
    with patch.object(stats, "_graphql", github):
        return stats.fetch("example", "token", now=datetime(2026, 11, 9, 12, tzinfo=timezone.utc))


def sample(**changes) -> dict:
    return {**json.loads(SAMPLE.read_text(encoding="utf-8")), **changes}


def card(raw: dict, profile=None, today: date = date(2026, 11, 9)) -> str:
    """The dark activity card for a snapshot, as on the sample's last day."""
    return cards.activity(stats.summarize(raw, profile or {}, today), OCTICONS, THEMES[0])


def run_build(*args, environment=None) -> None:
    """build.main with exactly this environment (none: a maintainer's machine), without its progress lines."""
    with patch.dict(os.environ, environment or {}, clear=True), redirect_stdout(io.StringIO()):
        build.main([str(arg) for arg in args])


def names(directory: Path) -> list:
    return sorted(path.name for path in directory.iterdir())


class LanguageFetchTests(unittest.TestCase):
    """Language shares are worked out from bytes, so every language of a repository must arrive."""

    def test_every_language_of_a_repository_is_fetched(self):
        # (languages in the repository, extra requests for its later pages)
        for count, later_pages in ((4, 0), (12, 0), (100, 0), (101, 1), (250, 2)):
            with self.subTest(languages=count):
                github = FakeGitHub(repos={"app": [(f"L{n}", 1000 - n) for n in range(count)]})
                languages = fetch(github)["repos"][0]["languages"]
                self.assertEqual(len(languages), count)
                self.assertEqual(sum(language["size"] for language in languages), sum(1000 - n for n in range(count)))
                self.assertEqual(len(github.queries), 2 + later_pages)  # the user page and the calendar years

    def test_shares_count_the_smallest_languages_too(self):
        # 15 evenly sized languages: cut to the 10 largest, the first would read 11% instead of 7.5%.
        sizes = [(f"L{n:02}", 1000 - 10 * n) for n in range(15)]
        total = sum(size for _, size in sizes)
        languages = stats.top_languages(fetch(FakeGitHub(repos={"app": sizes}))["repos"], [], [])
        self.assertEqual([language.name for language in languages], ["L00", "L01", "L02", "L03", "L04", "Other"])
        self.assertAlmostEqual(languages[0].share, 1000 / total)
        self.assertAlmostEqual(languages[-1].share, sum(size for _, size in sizes[5:]) / total)

    def test_repository_that_vanishes_between_pages_is_an_error(self):
        github = FakeGitHub(repos={"app": [(f"L{n}", 1000 - n) for n in range(150)]})
        github.gone.add("app")
        with self.assertRaisesRegex(RuntimeError, "GitHub repository example/app not found"):
            fetch(github)


class SnapshotShapeTests(unittest.TestCase):
    def test_sample_snapshot_has_the_shape_fetch_returns(self):
        fetched = fetch(FakeGitHub(repos={"app": [("Python", 10)]}, days={"2026-11-09": 1}))
        shipped = sample()
        self.assertEqual(set(shipped), set(fetched))
        self.assertEqual(set(shipped["repos"][0]), set(fetched["repos"][0]))
        self.assertEqual(set(shipped["repos"][0]["languages"][0]), set(fetched["repos"][0]["languages"][0]))
        self.assertEqual(list(shipped["days"]), sorted(shipped["days"]))  # as fetch writes them


class PrivateContributionTests(unittest.TestCase):
    """The calendar behind the total and streaks counts private contributions when the profile
    shows them, unlike every other number on the card: the card has to say so."""

    def test_fetch_adds_up_the_private_contributions_of_every_year(self):
        github = FakeGitHub(days={"2025-12-31": 500, "2026-11-08": 72}, private={2025: 500, 2026: 51})
        raw = fetch(github)
        self.assertEqual(sum(raw["days"].values()), 572)
        self.assertEqual(raw["privateContributions"], 551)

    def test_card_says_that_private_contributions_are_counted(self):
        svg = card(sample(privateContributions=24))
        self.assertIn(">24 in private repos<", svg)
        self.assertIn(f">{cards.PRIVATE_NOTE}<", svg)
        # The title is what a screen reader, or a hover, gives.
        self.assertIn("80 contributions (24 in private repositories), current streak 6 days", svg)
        self.assertIn(f"longest streak 9 days; {cards.PRIVATE_NOTE}<", svg)

    def test_card_without_private_contributions_says_nothing_about_them(self):
        without_key = sample()
        del without_key["privateContributions"]  # a snapshot saved before fetch reported them
        for raw in (sample(privateContributions=0), without_key):
            svg = card(raw)
            self.assertNotIn("private", svg)
            self.assertIn(">Jul 2025 – present<", svg)
            self.assertIn("80 contributions, current streak 6 days", svg)

    def test_private_note_fits_the_column_under_the_total(self):
        for count in (1, 551, 9_999, 123_456, 999_949):
            svg = card(sample(days={"2026-11-09": count}, privateContributions=count))
            note = re.search(r">([^<>]* in private repos)<", svg).group(1)
            self.assertLessEqual(len(note), 23, note)  # the width cards._span keeps the other notes to

    def test_private_count_is_capped_at_a_date_bounded_total(self):
        # A day before the snapshot's last one leaves later days out of the total (7 here), but the
        # snapshot has a single private count (24) for the whole calendar.
        summary = stats.summarize(sample(), {}, date(2026, 10, 12))
        self.assertEqual((summary.contributions, summary.private_contributions), (7, 7))
        whole = stats.summarize(sample(), {}, date(2026, 11, 9))
        self.assertEqual((whole.contributions, whole.private_contributions), (80, 24))


class LanguagePanelTests(unittest.TestCase):
    """The panel is empty for two different reasons, and the card counts excluded repos under Repos."""

    RAW = sample(publicRepos=1, repos=[
        {"name": "example", "stars": 0, "languages": [{"name": "Python", "color": "#3572A5", "size": 39006}]},
    ])

    def test_excluded_code_is_not_called_no_public_code(self):
        for options in ({"exclude_repos": ["Example"]}, {"hide": ["python"]}):
            with self.subTest(languages=options):
                svg = card(self.RAW, {"languages": options})
                self.assertIn(">No languages to show<", svg)
                self.assertIn(">All public code is excluded in profile.json.<", svg)
                self.assertNotIn("No public code yet", svg)

    def test_no_public_code_keeps_its_own_message(self):
        svg = card(sample(publicRepos=0, repos=[]), {"languages": {"exclude_repos": ["Example"]}})
        self.assertIn(">No public code yet<", svg)
        self.assertIn(">Languages from public repos will show up here.<", svg)

    def test_languages_are_listed_when_some_remain(self):
        svg = card(self.RAW, {"languages": {"exclude_repos": ["other"]}})
        self.assertIn(">Python<", svg)
        self.assertNotIn("No languages to show", svg)


class WorkflowTests(unittest.TestCase):
    """README.md does not show the activity card, so the workflow must not fetch or commit it."""

    def test_workflow_build_makes_no_request_and_draws_no_activity_card(self):
        no_request = AssertionError("the plain workflow build must not call GitHub")
        with tempfile.TemporaryDirectory() as temporary, patch.object(stats, "_graphql", side_effect=no_request):
            run_build("--output-dir", temporary, environment=WORKFLOW)
            self.assertEqual(names(Path(temporary)), CARDS)

    def test_activity_flag_draws_the_card_from_fetched_data(self):
        github = FakeGitHub(repos={"app": [("Python", 10)]}, days={"2026-11-09": 3})
        with tempfile.TemporaryDirectory() as temporary, patch.object(stats, "_graphql", github):
            run_build("--activity", "--output-dir", temporary, environment=WORKFLOW)
            self.assertEqual(names(Path(temporary)), sorted(ACTIVITY + CARDS))
            self.assertIn(" on GitHub: 3 contributions, ", (Path(temporary) / ACTIVITY[0]).read_text("utf-8"))
        self.assertEqual(len(github.queries), 2)

    def test_activity_flag_is_refused_outside_the_workflow(self):
        # A personal token would count private repositories on a public card.
        no_request = AssertionError("--activity must not call GitHub outside the workflow")
        with tempfile.TemporaryDirectory() as temporary, patch.object(stats, "_graphql", side_effect=no_request):
            out = Path(temporary) / "out"
            with self.assertRaises(SystemExit) as stopped:
                run_build("--activity", "--output-dir", out, environment={"GITHUB_TOKEN": "personal"})
            self.assertIn("--activity only runs in the GitHub workflow", str(stopped.exception))
            self.assertFalse(out.exists())

    def test_failed_fetch_writes_nothing(self):
        down = RuntimeError("GitHub GraphQL error: down")
        with tempfile.TemporaryDirectory() as temporary, patch.object(stats, "_graphql", side_effect=down):
            out = Path(temporary) / "out"
            with self.assertRaises(RuntimeError):
                run_build("--activity", "--output-dir", out, environment=WORKFLOW)
            self.assertFalse(out.exists())

    def test_card_is_drawn_and_committed_only_while_the_readme_shows_it(self):
        shown = "assets/activity-" in (ROOT / "README.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-profile.yml").read_text(encoding="utf-8")
        drawn = any("--activity" in line.split("#")[0] for line in workflow.splitlines())
        committed = sorted(path.name for path in (ROOT / "assets").glob("activity-*.svg"))
        self.assertEqual(drawn, shown, "build-profile.yml should pass --activity exactly when README.md embeds the card")
        if not shown:  # once it is shown again, the workflow's first run adds the files
            self.assertEqual(committed, [], "README.md does not embed the activity card, so assets/ should not hold it")


class PreviewLocationTests(unittest.TestCase):
    """A card drawn from a snapshot is a preview: it must never land where `git add assets` picks it up."""

    def test_data_preview_goes_to_preview_and_leaves_assets_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets, preview = Path(temporary) / "assets", Path(temporary) / "preview"
            with patch.object(build, "ASSETS", assets), patch.object(build, "PREVIEW", preview):
                run_build("--data", SAMPLE)
            self.assertEqual(names(preview), sorted(ACTIVITY + CARDS))
            self.assertFalse(assets.exists())

    def test_data_preview_is_refused_inside_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary) / "assets"
            for out in (assets, assets / "preview"):
                with self.subTest(output_dir=str(out.relative_to(temporary))), patch.object(build, "ASSETS", assets):
                    with self.assertRaises(SystemExit) as stopped:
                        run_build("--data", SAMPLE, "--output-dir", out)
                    self.assertIn("must not end up in assets/", str(stopped.exception))
            self.assertFalse(assets.exists())

    def test_data_preview_is_refused_under_another_name_for_assets(self):
        # A symlink names the same directory, and so does another spelling on a disk that ignores case.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            (root / "published").symlink_to(assets, target_is_directory=True)
            others = [root / "published", root / "published" / "preview"]
            if (root / "ASSETS").exists():  # this disk ignores case, as macOS and Windows disks usually do
                others += [root / "ASSETS", root / "Assets" / "preview"]
            for out in others:
                with self.subTest(output_dir=str(out.relative_to(root))), patch.object(build, "ASSETS", assets):
                    with self.assertRaises(SystemExit) as stopped:
                        run_build("--data", SAMPLE, "--output-dir", out)
                    self.assertIn("must not end up in assets/", str(stopped.exception))
            self.assertEqual(names(assets), [])

    def test_plain_build_still_writes_to_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets, preview = Path(temporary) / "assets", Path(temporary) / "preview"
            with patch.object(build, "ASSETS", assets), patch.object(build, "PREVIEW", preview):
                run_build()
            self.assertEqual(names(assets), CARDS)
            self.assertFalse(preview.exists())

    def test_git_ignores_previews_and_the_old_snapshot_name(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        self.assertEqual(build.PREVIEW, ROOT / "preview")
        self.assertIn("preview/", ignored)
        self.assertIn("stats.json", ignored)  # where the old usage line had a snapshot saved


if __name__ == "__main__":
    unittest.main()
