#!/usr/bin/env python3
"""Render every profile card into assets/ (one light and one dark SVG each).

    python3 scripts/build.py                     # banner and tech stack
    python3 scripts/build.py --data stats.json   # also preview the activity card from a snapshot

The activity card is only built inside GitHub Actions: the workflow's token sees public
data only, while a personal token would count private repositories on a public page.
Edit profile.json to change the text and tech stack; never edit the SVGs by hand.
Standard library only, so it runs on any GitHub Actions runner without installing anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "profile-card-builder"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


FREE_LICENSES = {"CC0-1.0", "Unlicense"}  # no attribution or notice needed


def fetch_brands(slugs: list) -> dict:
    """Look up logos missing from icons.json on Simple Icons, one entry per slug.

    A logo whose licence Simple Icons records with conditions (MIT, CC BY, ...)
    comes back without its shape, so it is drawn as a letter tile until it is
    credited in THIRD_PARTY_NOTICES.md. Every other logo comes back complete with
    its source, so its terms can be checked. A slug Simple Icons doesn't know
    comes back as a bare title. A network failure stops the build, so a CDN
    hiccup never publishes letter tiles in place of real logos.
    """
    found = {}
    try:
        catalog = {icon.get("slug"): icon for icon in json.loads(_download(f"{SIMPLE_ICONS}/data/simple-icons.json"))}
        for slug in slugs:
            icon = catalog.get(slug)
            if not icon:
                found[slug] = {"title": slug, "note": "not in Simple Icons"}
                continue
            entry = {"title": icon["title"], "source": icon.get("source", "")}
            license_type = (icon.get("license") or {}).get("type")
            if license_type:
                entry["license"] = license_type
            if license_type and license_type not in FREE_LICENSES:
                found[slug] = entry
                continue
            svg_text = _download(f"{SIMPLE_ICONS}/icons/{slug}.svg").decode()
            path = re.search(r'<path d="([MmLlHhVvCcSsQqTtAaZz0-9.,\s+\-eE]+)"', svg_text)
            if path and re.fullmatch(r"[0-9A-Fa-f]{6}", icon.get("hex", "")):
                found[slug] = {**entry, "hex": icon["hex"], "path": path.group(1)}
                print(f"  + {icon['title']} logo added; check its terms at {entry['source'] or 'simpleicons.org'}")
            else:
                found[slug] = {**entry, "note": "unexpected Simple Icons data"}
    except (OSError, ValueError) as error:
        sys.exit(f"Couldn't fetch logos from Simple Icons ({error}); try again later.")
    return found


def stack_groups(profile: dict, icons: dict) -> list:
    """profile.json stack entries are a Simple Icons slug, or {"icon": slug, "label": text}."""
    config = profile.get("stack") or []
    entries = [{"icon": item} if isinstance(item, str) else item for group in config for item in group["items"]]
    brands = icons["brands"]
    missing = sorted({e["icon"] for e in entries if e.get("icon") and e["icon"] not in brands})
    if missing:
        # Cache every answer, refusals included, so later builds need no network.
        # The workflow commits this file along with the cards.
        brands.update(fetch_brands(missing))
        ICONS.write_text(json.dumps(icons, indent=2) + "\n", encoding="utf-8")
        print(f"  cached {', '.join(missing)} in {ICONS.relative_to(ROOT)}")
    for slug in sorted({e["icon"] for e in entries if e.get("icon")}):
        brand = brands[slug]
        if "path" not in brand:
            reason = brand.get("note") or f"its {brand.get('license', 'licence')} logo needs a credit in THIRD_PARTY_NOTICES.md"
            print(f"  ! {brand['title']}: letter tile, {reason} (delete its scripts/icons.json entry to look it up again)",
                  file=sys.stderr)

    groups = []
    for group in config:
        items = []
        for item in group["items"]:
            entry = {"icon": item} if isinstance(item, str) else item
            data = brands.get(entry.get("icon") or "", {})
            label = entry.get("label") or data.get("title") or entry.get("icon", "?")
            items.append(cards.Brand(label, data.get("hex"), data.get("path")))
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
    icons = json.loads(ICONS.read_text(encoding="utf-8"))
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
