#!/usr/bin/env python3
"""Render every profile card into assets/ (one light and one dark SVG each).

    python3 scripts/build.py                      # live numbers: needs GITHUB_TOKEN or `gh auth login`
    python3 scripts/build.py --data stats.json    # offline, from a saved snapshot
    python3 scripts/build.py --save-data stats.json

Edit profile.json to change the text and tech stack; never edit the SVGs by hand.
Standard library only, so it runs on any GitHub Actions runner without installing anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import cards
import stats
from svg import THEMES

ROOT = Path(__file__).resolve().parent.parent
ICONS = Path(__file__).resolve().parent / "icons.json"
SIMPLE_ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@16"
MAX_TYPING_CHARS = 38  # longer lines would run into the network graphic


def github_token() -> str:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        if result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    sys.exit("No GitHub token: set GITHUB_TOKEN, run `gh auth login`, or pass --data FILE.")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "profile-card-builder"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def fetch_brands(slugs: list) -> dict:
    """Look up logos missing from icons.json on Simple Icons. Unknown or unreachable -> {}."""
    found = {}
    try:
        catalog = json.loads(_download(f"{SIMPLE_ICONS}/data/simple-icons.json"))
    except (OSError, ValueError) as error:
        print(f"  ! couldn't reach Simple Icons ({error}); using letter tiles", file=sys.stderr)
        return found
    meta = {icon.get("slug"): icon for icon in catalog}
    for slug in slugs:
        icon = meta.get(slug)
        try:
            svg_text = _download(f"{SIMPLE_ICONS}/icons/{slug}.svg").decode() if icon else ""
        except OSError:
            svg_text = ""
        path = re.search(r'<path d="([MmLlHhVvCcSsQqTtAaZz0-9.,\s+\-eE]+)"', svg_text)
        if icon and path and re.fullmatch(r"[0-9A-Fa-f]{6}", icon.get("hex", "")):
            found[slug] = {"title": icon["title"], "hex": icon["hex"], "path": path.group(1)}
        else:
            print(f"  ! no Simple Icons logo for {slug!r}; using a letter tile", file=sys.stderr)
    return found


def stack_groups(profile: dict, icons: dict) -> list:
    """profile.json stack entries are a Simple Icons slug, or {"icon": slug, "label": text}."""
    entries = [{"icon": item} if isinstance(item, str) else item
               for group in profile["stack"] for item in group["items"]]
    missing = sorted({e["icon"] for e in entries if e.get("icon") and e["icon"] not in icons})
    known = {**icons, **(fetch_brands(missing) if missing else {})}

    groups = []
    for group in profile["stack"]:
        brands = []
        for item in group["items"]:
            entry = {"icon": item} if isinstance(item, str) else item
            data = known.get(entry.get("icon") or "", {})
            label = entry.get("label") or data.get("title") or entry.get("icon", "?")
            brands.append(cards.Brand(label, data.get("hex"), data.get("path")))
        groups.append((group["group"], brands))
    return groups


def check(profile: dict) -> None:
    if not str(profile.get("name", "")).strip():
        sys.exit("profile.json: \"name\" is empty.")
    lines = profile.get("typing") or []
    if not lines:
        sys.exit("profile.json: add at least one line to \"typing\".")
    for line in lines:
        if line != line.strip() or len(line) > MAX_TYPING_CHARS:
            sys.exit(f"profile.json: typing line {line!r} must be trimmed and at most {MAX_TYPING_CHARS} characters.")


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)} ({len(content.encode()) / 1024:.1f} KB)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, help="render from this stats snapshot instead of the GitHub API")
    parser.add_argument("--save-data", type=Path, help="also save the fetched stats to this file")
    parser.add_argument("--today", type=date.fromisoformat, help="treat this YYYY-MM-DD as today")
    args = parser.parse_args(argv)

    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    icons = json.loads(ICONS.read_text(encoding="utf-8"))
    check(profile)
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)

    groups = stack_groups(profile, icons["brands"])
    for theme in THEMES:
        write(out / f"header-{theme.name}.svg", cards.header(profile, theme))
        write(out / f"stack-{theme.name}.svg", cards.stack(groups, theme))

    login = profile.get("login") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if args.data:
        raw = json.loads(args.data.read_text(encoding="utf-8"))
    else:
        raw = stats.fetch(login, github_token())
        if args.save_data:
            args.save_data.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    today = args.today or datetime.now(timezone.utc).date()
    summary = stats.summarize(raw, profile, today)
    for theme in THEMES:
        write(out / f"activity-{theme.name}.svg", cards.activity(summary, icons["octicons"], theme))

    print(f"  {summary.contributions} contributions, streak {summary.current.length} "
          f"(best {summary.longest.length}), {len(summary.languages)} languages")


if __name__ == "__main__":
    main()
