#!/usr/bin/env python3
"""Render the profile cards into assets/ (one light and one dark SVG each).

    python3 scripts/build.py                                   # banner and tech stack
    python3 scripts/build.py --check                           # render and validate them, write nothing
    python3 scripts/build.py --data scripts/sample-stats.json  # preview them and the activity card

README.md no longer shows the activity card, so the workflow doesn't draw it. To bring it
back, embed assets/activity-*.svg in README.md again and have the workflow run this with
--activity and GITHUB_TOKEN set. --activity works only inside GitHub Actions: the
workflow's token sees public data only, while a personal token would count private
repositories on a public page. The one exception is the contribution calendar behind the
total and streaks: when the profile is set to show private contributions, it counts them
anonymously for any token, so the card says how many of the total they are and that the
streaks count them too.
A --data preview is drawn as of the snapshot's last day (--today overrides it) and goes to
preview/, which git ignores, so it can't be committed along with assets/. --output-dir sends
any run's cards elsewhere, though never a --data preview into assets/. Every card is rendered
and checked before any file is written.
Edit profile.json to change the text and tech stack; never edit the SVGs by hand.
Logos come only from scripts/icons.json, where they are added by hand after checking
their terms; a technology without an entry there is drawn as a letter tile.
Standard library only, so it runs on any GitHub Actions runner without installing anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import cards
import stats
from svg import THEMES

ROOT = Path(__file__).resolve().parent.parent
ICONS = Path(__file__).resolve().parent / "icons.json"
ASSETS = ROOT / "assets"  # the published cards: README.md embeds them and the workflow commits them
PREVIEW = ROOT / "preview"  # where --data previews go; .gitignore keeps it out of commits
MAX_TYPING_CHARS = 38  # longer lines would run into the network graphic
# A logo path goes straight into d="...": accept SVG path data only (a moveto, then commands and numbers).
PATH_DATA = re.compile(r"[ \t\r\n]*[Mm][MmLlHhVvCcSsQqTtAaZz0-9.,+\-eE \t\r\n]*")


def load_json(path: Path, fix: str) -> dict:
    """A hand-edited JSON file, refusing duplicate keys (json would silently keep the last one)."""
    def no_duplicates(pairs):
        keys = [key for key, _ in pairs]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            sys.exit(f"{path.name}: duplicate key {', '.join(repeated)}; {fix}")
        return dict(pairs)

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def load_icons(path: Path = ICONS) -> dict:
    return load_json(path, "keep one entry per logo.")


def warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=Tech stack card::{message}")  # shows on the workflow run's summary


def brand_for(slug: str, label: str, data: dict) -> cards.Brand:
    if "art" in data:
        for key in ("art", "art_dark"):
            art = data.get(key)
            if key == "art_dark" and art is None:
                continue  # optional: dark cards then use the art as well
            if not (isinstance(art, dict) and art.get("viewBox") and art.get("body")):
                sys.exit(f"scripts/icons.json: {slug} {key} needs a viewBox and a body.")
        return cards.Brand(label, None, None, data["art"], data.get("art_dark"))
    if "path" in data:
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", str(data.get("hex", ""))):
            sys.exit(f"scripts/icons.json: {slug} has a path but no 6-digit hex colour.")
        if not (isinstance(data["path"], str) and PATH_DATA.fullmatch(data["path"])):
            sys.exit(f"scripts/icons.json: {slug} path must be SVG path data only: "
                     "the value of d=\"...\", without quotes or tags.")
        return cards.Brand(label, data["hex"], data["path"])
    return cards.Brand(label, None, None)


def stack_groups(profile: dict, icons: dict) -> list:
    """profile.json stack entries are an icons.json slug, or {"icon": slug, "label": text}."""
    groups = []
    for group in profile.get("stack") or []:
        items = []
        for item in group["items"]:
            entry = {"icon": item} if isinstance(item, str) else item
            slug = entry.get("icon") or ""
            data = icons["brands"].get(slug, {}) if slug else {}
            label = entry.get("label") or data.get("title") or slug or "?"
            if slug and "art" not in data and "path" not in data:
                # No entry, or one without a shape (a copied metadata record, a misspelt key...).
                where = "its scripts/icons.json entry has no path or art" if data else "no logo in scripts/icons.json"
                warn(f"{label}: {where}, so it is drawn as a letter tile. "
                     "Add one there by hand after checking its terms (see THIRD_PARTY_NOTICES.md).")
            items.append(brand_for(slug, label, data))
        groups.append((group["group"], items))
    return groups


def check(profile: dict) -> None:
    if not str(profile.get("name", "")).strip():
        sys.exit("profile.json: \"name\" is empty.")
    lines = profile.get("typing") or []
    if not lines:
        sys.exit("profile.json: add at least one line to \"typing\".")
    for line in lines:
        # SVG collapses repeated spaces, which would break the one-cell-per-character typing effect.
        if line != line.strip() or re.search(r"[^\S ]| {2}", line) or len(line) > MAX_TYPING_CHARS:
            sys.exit(f"profile.json: typing line {line!r} must be trimmed, use single spaces "
                     f"and be at most {MAX_TYPING_CHARS} characters.")


def write(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".profile-", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"  wrote {path} ({len(content.encode()) / 1024:.1f} KB)")


def snapshot_summary(path: Path, profile: dict, today: Optional[date]) -> stats.Summary:
    """A --data stats snapshot, summarized; a missing key is named instead of crashing.

    So is a days key that is not a date: stats.summarize reads every one, whatever its count.
    Without a --today, it is summarized as of its last day: fetch keeps the calendar up to the
    day it ran, so counting from the wall clock would show any older snapshot's streak as broken.
    """
    def day(key: str) -> date:
        try:
            return date.fromisoformat(key)
        except ValueError:
            sys.exit(f"{path}: days key {key!r} is not a YYYY-MM-DD date; "
                     "scripts/sample-stats.json shows the format.")

    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        days = [day(key) for key in raw["days"]]
        if today is None:
            today = max(days) if days else datetime.now(timezone.utc).date()
        return stats.summarize(raw, profile, today)
    except KeyError as error:
        sys.exit(f"{path}: no {error} key; scripts/sample-stats.json shows the format.")


def public_summary(profile: dict, today: date) -> stats.Summary:
    """The workflow's own numbers: its token sees public data only."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        sys.exit("--activity only runs in the GitHub workflow, whose token sees public data only. "
                 "Pass --data FILE to preview the activity card instead.")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set for this workflow step.")
    login = profile.get("login") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    return stats.summarize(stats.fetch(login, token), profile, today)


def inside_assets(directory: Path) -> bool:
    """Whether a resolved directory is assets/ or lies inside it, whatever name it goes by."""
    for candidate in (directory, *directory.parents):
        if candidate == ASSETS.resolve():
            return True
        try:
            if candidate.samefile(ASSETS):  # another spelling, such as Assets on a disk that ignores case
                return True
        except OSError:
            pass  # one of them doesn't exist (yet), so they are not one directory
    return False


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    card = parser.add_mutually_exclusive_group()
    card.add_argument("--activity", action="store_true",
                      help="also draw the activity card from public GitHub data (GitHub Actions only)")
    card.add_argument("--data", type=Path, help="preview: also draw the activity card, from this stats snapshot "
                                                "(scripts/sample-stats.json shows the format)")
    parser.add_argument("--today", type=date.fromisoformat,
                        help="treat this YYYY-MM-DD as today (default: the --data snapshot's last day, "
                             "else the current UTC date)")
    parser.add_argument("--output-dir", type=Path,
                        help="directory for generated SVG cards (default: assets, or preview with --data)")
    parser.add_argument("--check", action="store_true",
                        help="render and validate every selected card without writing files")
    args = parser.parse_args(argv)

    profile = load_json(ROOT / "profile.json", "merge them into one.")
    icons = load_icons()
    check(profile)
    out = (args.output_dir or (PREVIEW if args.data else ASSETS)).resolve()
    if args.data and inside_assets(out):
        sys.exit("--data draws a preview from a snapshot, which must not end up in assets/ (the published "
                 "cards). Leave out --output-dir to use preview/, or name a directory outside assets/.")
    rendered = {}

    groups = stack_groups(profile, icons)
    for theme in THEMES:
        rendered[f"header-{theme.name}.svg"] = cards.header(profile, theme)
        rendered[f"stack-{theme.name}.svg"] = cards.stack(groups, theme)

    if args.data:
        summary = snapshot_summary(args.data, profile, args.today)
    elif args.activity:
        summary = public_summary(profile, args.today or datetime.now(timezone.utc).date())
    else:
        print("  skipped the activity card, which the profile doesn't show; "
              "pass --data scripts/sample-stats.json to preview it.")
        summary = None
    if summary is not None:
        for theme in THEMES:
            rendered[f"activity-{theme.name}.svg"] = cards.activity(summary, icons["octicons"], theme)
        print(f"  {summary.contributions} contributions, streak {summary.current.length} "
              f"(best {summary.longest.length}), {len(summary.languages)} languages")
    # Validate the complete set before replacing any existing card.
    for name, content in rendered.items():
        if ET.fromstring(content).tag != "{http://www.w3.org/2000/svg}svg":
            raise ValueError(f"{name}: expected an SVG document")
    if args.check:
        print(f"  validated {len(rendered)} SVG cards; no files written")
    else:
        out.mkdir(parents=True, exist_ok=True)
        for name, content in rendered.items():
            write(out / name, content)


if __name__ == "__main__":
    main()
