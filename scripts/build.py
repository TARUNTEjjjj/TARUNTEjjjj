#!/usr/bin/env python3
"""Render every profile card into assets/ (one light and one dark SVG each).

    python3 scripts/build.py                     # banner and tech stack
    python3 scripts/build.py --data stats.json   # also preview the activity card from a snapshot

The activity card is only built inside GitHub Actions: the workflow's token sees public
data only, while a personal token would count private repositories on a public page.
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
from datetime import date, datetime, timezone
from pathlib import Path

import cards
import stats
from svg import THEMES

ROOT = Path(__file__).resolve().parent.parent
ICONS = Path(__file__).resolve().parent / "icons.json"
MAX_TYPING_CHARS = 38  # longer lines would run into the network graphic


def load_icons(path: Path = ICONS) -> dict:
    """icons.json, refusing duplicate keys (json would silently keep the last one)."""
    def no_duplicates(pairs):
        keys = [key for key, _ in pairs]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            sys.exit(f"{path.name}: duplicate key {', '.join(repeated)}; keep one entry per logo.")
        return dict(pairs)

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=Tech stack card::{message}")  # shows on the workflow run's summary


def brand_for(slug: str, label: str, data: dict) -> cards.Brand:
    if "art" in data:
        for key in ("art", "art_dark"):
            art = data.get(key)
            if art is not None and not (isinstance(art, dict) and art.get("viewBox") and art.get("body")):
                sys.exit(f"scripts/icons.json: {slug} {key} needs a viewBox and a body.")
        return cards.Brand(label, None, None, data["art"], data.get("art_dark"))
    if "path" in data:
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", str(data.get("hex", ""))):
            sys.exit(f"scripts/icons.json: {slug} has a path but no 6-digit hex colour.")
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
            if slug and not data:
                warn(f"{label}: no logo in scripts/icons.json, so it is drawn as a letter tile. "
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
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)} ({len(content.encode()) / 1024:.1f} KB)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, help="render the activity card from this stats snapshot")
    parser.add_argument("--today", type=date.fromisoformat, help="treat this YYYY-MM-DD as today")
    args = parser.parse_args(argv)

    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    icons = load_icons()
    check(profile)
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)

    groups = stack_groups(profile, icons)
    for theme in THEMES:
        write(out / f"header-{theme.name}.svg", cards.header(profile, theme))
        write(out / f"stack-{theme.name}.svg", cards.stack(groups, theme))

    if args.data:
        raw = json.loads(args.data.read_text(encoding="utf-8"))
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN is not set for this workflow step.")
        login = profile.get("login") or os.environ.get("GITHUB_REPOSITORY_OWNER")
        raw = stats.fetch(login, token)
    else:
        print("  skipped the activity card: only the GitHub workflow builds it, because its token sees "
              "public data only. Pass --data FILE to preview it.")
        return
    today = args.today or datetime.now(timezone.utc).date()
    summary = stats.summarize(raw, profile, today)
    for theme in THEMES:
        write(out / f"activity-{theme.name}.svg", cards.activity(summary, icons["octicons"], theme))

    print(f"  {summary.contributions} contributions, streak {summary.current.length} "
          f"(best {summary.longest.length}), {len(summary.languages)} languages")


if __name__ == "__main__":
    main()
