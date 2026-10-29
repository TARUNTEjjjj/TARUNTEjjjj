"""The three profile cards: animated header, tech stack and GitHub activity.

Every function returns a complete, self-contained SVG document for one theme.
Animations are CSS + SMIL only, which GitHub renders inside <img> tags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from stats import Streak, Summary
from svg import MONO_ADVANCE, Theme, contrast, document, esc, num, text_width

WIDTH = 1200

# --------------------------------------------------------------------- header

# Typing animation timing, in seconds.
TYPE_STEP, DELETE_STEP, HOLD, GAP = 0.07, 0.03, 2.2, 0.45

LAYERS = (3, 5, 5, 2)
# Signal paths drawn through the network: (input node, [(hidden-1, hidden-2, output), ...]).
# Hand-picked rather than random so the SVG is identical on every build.
WAVES = (
    (1, ((0, 1, 0), (3, 3, 1))),
    (0, ((2, 0, 0), (4, 2, 1))),
    (2, ((1, 4, 1), (3, 2, 0))),
)
PERIOD, HOP = 4.8, 0.7


def _typing_schedule(lines: list) -> tuple[list, float]:
    """For each line, the (time, visible characters) steps of one full loop."""
    t, schedule = 0.0, []
    for line in lines:
        steps = [(t, 0)]
        steps += [(t + k * TYPE_STEP, k) for k in range(1, len(line) + 1)]
        t += len(line) * TYPE_STEP + HOLD
        for k in range(len(line) - 1, -1, -1):
            t += DELETE_STEP
            steps.append((t, k))
        t += GAP
        schedule.append(steps)
    return schedule, t


def _discrete(attribute: str, steps: list, period: float) -> str:
    """A looping SMIL animation that jumps between (time, value) steps."""
    times, values = [], []
    for t, value in steps:
        key = f"{t / period:.5f}"
        if times and key == times[-1]:
            values[-1] = num(value)  # same instant after rounding: the later value wins
            continue
        if values and values[-1] == num(value):
            continue
        times.append(key)
        values.append(num(value))
    times[0] = "0"
    return (f'<animate attributeName="{attribute}" dur="{num(period)}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{";".join(times)}" values="{";".join(values)}"/>')


def _network(t: Theme) -> tuple[str, str]:
    """A small neural net with signals pulsing through it. Returns (svg, css)."""
    xs, spacing, mid = (800, 910, 1020, 1130), 46, 150
    nodes = [[(xs[layer], mid + (j - (n - 1) / 2) * spacing) for j in range(n)]
             for layer, n in enumerate(LAYERS)]
    layer_color = (t.cyan, t.violet, t.violet, t.pink)
    edge_color = (t.cyan, t.violet, t.pink)

    def line(a, b) -> str:
        return f"M{num(a[0])} {num(a[1])}L{num(b[0])} {num(b[1])}"

    def delay(start: float) -> str:
        # Negative delays start every loop mid-flight, so nothing waits on page load.
        return f"animation-delay:{num(start % PERIOD - PERIOD)}s"

    edges = [line(a, b) for layer in range(len(LAYERS) - 1)
             for a in nodes[layer] for b in nodes[layer + 1]]
    parts = [f'<path class="edge" stroke="{t.border}" d="{"".join(edges)}"/>']

    glows = {}
    for w, (source, branches) in enumerate(WAVES):
        offset = w * PERIOD / len(WAVES)
        glows[(0, source, offset)] = None
        for branch in branches:
            path = (source,) + branch
            for layer in range(3):
                start = offset + layer * HOP
                a, b = nodes[layer][path[layer]], nodes[layer + 1][path[layer + 1]]
                parts.append(f'<path class="pulse" stroke="{edge_color[layer]}" pathLength="100" '
                             f'd="{line(a, b)}" style="{delay(start)}"/>')
                glows[(layer + 1, path[layer + 1], start + HOP)] = None
    for layer, j, at in glows:
        x, y = nodes[layer][j]
        parts.append(f'<circle class="glow" cx="{num(x)}" cy="{num(y)}" r="13" fill="{layer_color[layer]}" '
                     f'filter="url(#soft)" style="{delay(at - 0.08)}"/>')
    for layer, column in enumerate(nodes):
        for x, y in column:
            parts.append(f'<circle cx="{num(x)}" cy="{num(y)}" r="8" fill="{t.bg}" '
                         f'stroke="{layer_color[layer]}" stroke-width="2"/>'
                         f'<circle cx="{num(x)}" cy="{num(y)}" r="2.6" fill="{layer_color[layer]}"/>')

    travel = f"{HOP / PERIOD * 100:.2f}%"
    css = (
        ".edge{fill:none;stroke-width:1.2}"
        ".pulse{fill:none;stroke-width:3;stroke-linecap:round;stroke-dasharray:12 120;"
        f"stroke-dashoffset:-102;animation:pulse {num(PERIOD)}s cubic-bezier(.4,0,.6,1) infinite}}"
        f"@keyframes pulse{{0%{{stroke-dashoffset:14}}{travel}{{stroke-dashoffset:-102}}100%{{stroke-dashoffset:-102}}}}"
        f".glow{{opacity:0;animation:glow {num(PERIOD)}s ease-out infinite}}"
        "@keyframes glow{0%{opacity:0}4%{opacity:.85}24%{opacity:0}100%{opacity:0}}"
    )
    return "".join(parts), css


def header(profile: dict, t: Theme) -> str:
    height, x0 = 300, 64
    name = profile["name"]
    greeting = profile.get("greeting", "Hi there, I'm")
    lines = profile["typing"]

    name_size = min(80.0, 660 / text_width(name, 1, bold=True))
    size = 26
    cell = size * MONO_ADVANCE
    prompt = ">>>"
    tx, baseline = x0 + (len(prompt) + 1) * cell, 224

    # WebKit treats a zero-width clip as "no clip at all", so hidden text is clipped to
    # a sliver instead. Renderers without SMIL keep the base values: line one in full.
    hidden = 0.01
    schedule, period = _typing_schedule(lines)
    clips, texts, caret_steps = [], [], []
    for i, (line, steps) in enumerate(zip(lines, schedule)):
        full = len(line) * cell
        widths = [(s, max(k * cell, hidden)) for s, k in steps]
        clips.append(f'<clipPath id="type{i}"><rect x="{num(tx)}" y="{baseline - 30}" '
                     f'width="{num(full if i == 0 else hidden)}" height="42">'
                     f'{_discrete("width", widths, period)}</rect></clipPath>')
        texts.append(f'<text x="{num(tx)}" y="{baseline}" class="mono" font-size="{size}" fill="{t.text}" '
                     f'textLength="{num(full)}" lengthAdjust="spacing" '
                     f'clip-path="url(#type{i})">{esc(line)}</text>')
        caret_steps += [(s, tx + k * cell + 2) for s, k in steps]
    caret = (f'<rect class="caret" x="{num(tx + len(lines[0]) * cell + 2)}" y="{baseline - 21}" width="3" '
             f'height="27" rx="1" fill="{t.cyan}">{_discrete("x", caret_steps, period)}</rect>')

    network, network_css = _network(t)
    css = (
        network_css
        + ".caret{animation:blink 1.06s steps(1) infinite}@keyframes blink{50%{opacity:0}}"
        + ".still{display:none}"
        + "@media (prefers-reduced-motion:reduce){.pulse,.glow,.caret{animation:none}"
          ".typing{display:none}.still{display:inline}}"
    )
    body = (
        "<defs>"
        f'<clipPath id="card"><rect width="{WIDTH}" height="{height}" rx="20"/></clipPath>'
        f'<radialGradient id="glowA"><stop offset="0" stop-color="{t.glow_a}" stop-opacity="{t.glow_opacity}"/>'
        f'<stop offset="1" stop-color="{t.glow_a}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="glowB"><stop offset="0" stop-color="{t.glow_b}" stop-opacity="{t.glow_opacity * 0.8:.2f}"/>'
        f'<stop offset="1" stop-color="{t.glow_b}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="name" x2="1"><stop offset="0" stop-color="{t.name_from}"/>'
        f'<stop offset="1" stop-color="{t.name_to}"/></linearGradient>'
        f'<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
        f'<circle cx="2" cy="2" r="1.1" fill="{t.faint}"/></pattern>'
        '<linearGradient id="fade" x2="1"><stop offset=".3" stop-color="#fff" stop-opacity="0"/>'
        '<stop offset="1" stop-color="#fff"/></linearGradient>'
        f'<mask id="dotMask"><rect width="{WIDTH}" height="{height}" fill="url(#fade)"/></mask>'
        '<filter id="soft" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="4"/></filter>'
        + "".join(clips) +
        "</defs>"
        '<g clip-path="url(#card)">'
        f'<rect width="{WIDTH}" height="{height}" fill="{t.bg}"/>'
        '<ellipse cx="1010" cy="20" rx="460" ry="250" fill="url(#glowA)"/>'
        '<ellipse cx="660" cy="330" rx="420" ry="190" fill="url(#glowB)"/>'
        f'<rect width="{WIDTH}" height="{height}" fill="url(#dots)" mask="url(#dotMask)" opacity=".45"/>'
        f"{network}"
        f'<text x="{x0}" y="92" class="sans" font-size="26" font-weight="500" fill="{t.muted}">{esc(greeting)}</text>'
        f'<text x="{x0 - 3}" y="170" class="sans" font-size="{num(name_size)}" font-weight="700" '
        f'letter-spacing="-1.5" fill="url(#name)">{esc(name)}</text>'
        f'<text x="{x0}" y="{baseline}" class="mono" font-size="{size}" fill="{t.violet}" '
        f'textLength="{num(len(prompt) * cell)}" lengthAdjust="spacing">{esc(prompt)}</text>'
        f'<g class="typing">{"".join(texts)}{caret}</g>'
        f'<text x="{num(tx)}" y="{baseline}" class="mono still" font-size="{size}" fill="{t.text}">{esc(lines[0])}</text>'
        "</g>"
        f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{height - 1}" rx="19.5" fill="none" stroke="{t.border}"/>'
    )
    return document(WIDTH, height, f"{greeting} {name}: {lines[0]}", body, css)


# ---------------------------------------------------------------------- stack

@dataclass
class Brand:
    label: str
    hex: Optional[str]  # None -> monogram tile in the theme accent
    path: Optional[str]


PILL_H, TILE, PILL_FONT = 56, 36, 20
TILE_INSET = (PILL_H - TILE) / 2
LABEL_X = TILE_INSET + TILE + 14


def _pill_width(brand: Brand) -> float:
    return LABEL_X + text_width(brand.label, PILL_FONT) + 20


def _pill(x: float, y: float, brand: Brand, t: Theme) -> str:
    if brand.path:
        fill = f"#{brand.hex}"
        glyph_color = "#ffffff" if contrast("#ffffff", fill) >= 3 else "#0d1117"
        margin = 7
        scale = (TILE - 2 * margin) / 24  # Simple Icons are drawn on a 24px grid
        glyph = (f'<path transform="translate({num(TILE_INSET + margin)} {num(TILE_INSET + margin)}) '
                 f'scale({num(scale)})" fill="{glyph_color}" d="{brand.path}"/>')
    else:
        fill = t.violet
        glyph = (f'<text x="{num(TILE_INSET + TILE / 2)}" y="{num(TILE_INSET + TILE / 2 + 7)}" text-anchor="middle" '
                 f'class="sans" font-size="19" font-weight="700" fill="#ffffff">{esc(brand.label[:1].upper())}</text>')
    # Near-black logos (GitHub, NumPy...) would melt into a dark card without an outline.
    outline = f' stroke="{t.border}"' if contrast(fill, t.panel) < 1.5 else ""
    return (
        f'<g transform="translate({num(x)} {num(y)})">'
        f'<rect width="{num(_pill_width(brand))}" height="{PILL_H}" rx="14" fill="{t.panel}" stroke="{t.border}"/>'
        f'<rect x="{num(TILE_INSET)}" y="{num(TILE_INSET)}" width="{TILE}" height="{TILE}" rx="9" fill="{fill}"{outline}/>'
        f"{glyph}"
        f'<text x="{num(LABEL_X)}" y="{num(PILL_H / 2 + PILL_FONT * 0.36)}" class="sans" font-size="{PILL_FONT}" '
        f'font-weight="500" fill="{t.text}">{esc(brand.label)}</text>'
        "</g>"
    )


def stack(groups: list, t: Theme) -> str:
    """groups: [(group name, [Brand, ...]), ...]"""
    pad, gap_x, gap_y = 30, 12, 12
    label_font, tracking = 15, 1.4
    label_w = max(170, max(len(name) * (label_font * MONO_ADVANCE + tracking) for name, _ in groups) + 44)
    left = pad + label_w

    parts, y = [], pad
    for g, (name, brands) in enumerate(groups):
        accent = (t.violet, t.cyan, t.pink)[g % 3]
        parts.append(f'<rect x="{pad}" y="{y + PILL_H / 2 - 10}" width="3" height="20" rx="1.5" fill="{accent}"/>'
                     f'<text x="{pad + 14}" y="{y + PILL_H / 2 + 5}" class="mono" font-size="{label_font}" '
                     f'letter-spacing="{tracking}" fill="{t.faint}">{esc(name.upper())}</text>')
        x = left
        for brand in brands:
            w = _pill_width(brand)
            if x + w > WIDTH - pad and x > left:
                x, y = left, y + PILL_H + gap_y
            parts.append(_pill(x, y, brand, t))
            x += w + gap_x
        y += PILL_H + gap_y
    height = y - gap_y + pad

    names = ", ".join(b.label for _, brands in groups for b in brands)
    body = (
        f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{num(height - 1)}" rx="16" fill="{t.bg}" stroke="{t.border}"/>'
        + "".join(parts)
    )
    return document(WIDTH, height, f"Tech stack: {names}", body)


# ------------------------------------------------------------------- activity

def _count(n: int) -> str:
    if n >= 10_000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{n:,}"


def _day(d, today) -> str:
    return f"{d:%b} {d.day}" + (f", {d.year}" if d.year != today.year else "")


def _span(streak: Streak, today, empty: str) -> str:
    if not streak.length:
        return empty
    if streak.start == streak.end:
        return _day(streak.start, today)
    return f"{_day(streak.start, today)} – {_day(streak.end, today)}"


def _icon(paths: list, x: float, y: float, color: str, size: float = 16) -> str:
    scale = f" scale({num(size / 16)})" if size != 16 else ""
    inner = "".join(f'<path d="{d}"/>' for d in paths)
    return f'<g transform="translate({num(x)} {num(y)}){scale}" fill="{color}">{inner}</g>'


def _fit(text: str, size: float, max_width: float) -> str:
    if text_width(text, size) <= max_width:
        return text
    while text and text_width(text + "…", size) > max_width:
        text = text[:-1]
    return text + "…"


def activity(s: Summary, octicons: dict, t: Theme) -> str:
    height, left, right, split = 320, 40, 1160, 724
    lang_x = split + 40
    parts = []

    def label(x: float, text: str) -> str:
        return (f'<text x="{x}" y="52" class="mono" font-size="14" letter-spacing="1.6" '
                f'fill="{t.faint}">{esc(text)}</text>')

    parts += [label(left, "ACTIVITY"), label(lang_x, "TOP LANGUAGES")]

    def days(n: int) -> str:
        return "day" if n == 1 else "days"

    heroes = (
        ("graph", t.cyan, "Total contributions", _count(s.contributions), "",
         f"{s.joined:%b %Y} – present"),
        ("flame", t.pink, "Current streak", _count(s.current.length), days(s.current.length),
         _span(s.current, s.today, "no active streak")),
        ("trophy", t.violet, "Longest streak", _count(s.longest.length), days(s.longest.length),
         _span(s.longest, s.today, "no streak yet")),
    )
    for i, (icon, color, title, value, unit, sub) in enumerate(heroes):
        x = left + i * 224
        parts.append(_icon(octicons[icon], x, 74, color, size=17))
        parts.append(f'<text x="{x + 26}" y="88" class="sans" font-size="17" fill="{t.muted}">{esc(title)}</text>')
        parts.append(f'<text x="{x - 2}" y="144" class="sans" font-size="48" font-weight="700" '
                     f'fill="{t.text}">{esc(value)}</text>')
        if unit:
            ux = x + text_width(value, 48, bold=True) + 8
            parts.append(f'<text x="{num(ux)}" y="144" class="sans" font-size="20" fill="{t.muted}">{unit}</text>')
        parts.append(f'<text x="{x}" y="172" class="mono" font-size="14" fill="{t.faint}">{esc(sub)}</text>')

    parts.append(f'<path d="M{left} 198H{split - 40}" stroke="{t.border}"/>')
    small = (
        ("git-commit", "Commits", s.commits),
        ("git-pull-request", "Pull requests", s.pull_requests),
        ("issue-opened", "Issues", s.issues),
        ("repo", "Repos", s.repos),
        ("star", "Stars", s.stars),
        ("people", "Followers", s.followers),
    )
    for i, (icon, title, value) in enumerate(small):
        x = left + i * 109
        parts.append(_icon(octicons[icon], x, 220, t.muted))
        parts.append(f'<text x="{x + 24}" y="235" class="sans" font-size="22" font-weight="700" '
                     f'fill="{t.text}">{_count(value)}</text>')
        parts.append(f'<text x="{x}" y="262" class="sans" font-size="16" fill="{t.muted}">{title}</text>')

    parts.append(f'<path d="M{split} 36V276" stroke="{t.border}"/>')

    bar_w = right - lang_x
    if s.languages:
        x, segments = lang_x, []
        for i, lang in enumerate(s.languages):
            w = bar_w * lang.share
            gap = 2 if i < len(s.languages) - 1 else 0  # hairline between slices, none at the rounded end
            segments.append(f'<rect x="{num(x)}" y="72" width="{num(max(w - gap, 1.5))}" height="10" '
                            f'fill="{lang.color}"/>')
            x += w
        parts.append(f'<clipPath id="bar"><rect x="{lang_x}" y="72" width="{bar_w}" height="10" rx="5"/></clipPath>'
                     f'<g clip-path="url(#bar)">{"".join(segments)}</g>')
        for i, lang in enumerate(s.languages):
            cx, y = lang_x + (i // 3) * 206, 126 + (i % 3) * 40
            share = lang.share * 100
            pct = f"{share:.0f}%" if share >= 9.95 else f"{share:.1f}%"
            parts.append(f'<circle cx="{cx + 5}" cy="{y - 6}" r="5.5" fill="{lang.color}"/>'
                         f'<text x="{cx + 19}" y="{y}" class="sans" font-size="17" fill="{t.text}">'
                         f"{esc(_fit(lang.name, 17, 134))}</text>"
                         f'<text x="{cx + 196}" y="{y}" text-anchor="end" class="mono" font-size="15" '
                         f'fill="{t.muted}">{pct}</text>')
    else:
        parts.append(f'<rect x="{lang_x}" y="72" width="{bar_w}" height="10" rx="5" fill="{t.panel}" stroke="{t.border}"/>'
                     f'<text x="{lang_x}" y="128" class="sans" font-size="17" fill="{t.text}">No public code yet</text>'
                     f'<text x="{lang_x}" y="154" class="sans" font-size="15" fill="{t.muted}">'
                     "Languages from public repos will show up here.</text>")

    parts.append(f'<text x="{left}" y="300" class="mono" font-size="13" fill="{t.faint}">'
                 f"@{esc(s.login)} · on GitHub since {s.joined:%b %Y}</text>"
                 f'<text x="{right}" y="300" text-anchor="end" class="mono" font-size="13" fill="{t.faint}">'
                 f"updated {s.today.day} {s.today:%b %Y}</text>")

    title = (f"{s.login} on GitHub: {s.contributions:,} contributions, current streak {s.current.length} "
             f"{days(s.current.length)}, longest streak {s.longest.length} {days(s.longest.length)}")
    body = (f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{height - 1}" rx="16" fill="{t.bg}" stroke="{t.border}"/>'
            + "".join(parts))
    return document(WIDTH, height, title, body)
