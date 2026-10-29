"""Shared bits for the card renderers: themes, escaping, colours and text metrics."""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

# Typed text is stretched to exactly this advance (in em) with textLength, so the
# caret lands after the last character whatever monospace font the viewer has.
MONO_ADVANCE = 0.6


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    panel: str
    border: str
    text: str
    muted: str
    faint: str
    cyan: str
    violet: str
    pink: str
    name_from: str
    name_to: str
    glow_a: str
    glow_b: str
    glow_opacity: float


# Neutrals follow GitHub's own light/dark palettes so the cards sit naturally on
# the profile page; the accents are this profile's violet -> cyan identity.
THEMES = (
    Theme(
        name="dark",
        bg="#0d1117", panel="#161b22", border="#30363d",
        text="#e6edf3", muted="#9198a1", faint="#7d8590",
        cyan="#22d3ee", violet="#a78bfa", pink="#f472b6",
        name_from="#c4b5fd", name_to="#67e8f9",
        glow_a="#7c3aed", glow_b="#0891b2", glow_opacity=0.30,
    ),
    Theme(
        name="light",
        bg="#ffffff", panel="#f6f8fa", border="#d0d7de",
        text="#1f2328", muted="#59636e", faint="#6e7781",
        cyan="#0891b2", violet="#7c3aed", pink="#db2777",
        name_from="#6d28d9", name_to="#0e7490",
        glow_a="#c4b5fd", glow_b="#a5f3fc", glow_opacity=0.55,
    ),
)


def esc(value) -> str:
    return escape(str(value), {'"': "&quot;"})


def num(value: float) -> str:
    """Compact coordinate formatting: 12.0 -> '12', 12.345 -> '12.35'."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def document(width: float, height: float, title: str, body: str, style: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{num(width)}" height="{num(height)}" '
        f'viewBox="0 0 {num(width)} {num(height)}" role="img" aria-label="{esc(title)}">'
        f"<title>{esc(title)}</title>"
        f"<style>.sans{{font-family:{SANS}}}.mono{{font-family:{MONO}}}{style}</style>"
        f"{body}</svg>\n"
    )


# Advance widths of Helvetica/Arial for ASCII 32..126, in 1/1000 em. Close enough
# to the UI fonts GitHub visitors have; only used to size pills and columns.
_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
    278, 278, 584, 584, 584, 556, 1015,
    667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
    722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611,
    278, 278, 278, 469, 556, 333,
    556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
    556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500,
    334, 260, 334, 584,
)


def text_width(text: str, size: float, bold: bool = False) -> float:
    units = sum(_WIDTHS[ord(ch) - 32] if 32 <= ord(ch) < 127 else 600 for ch in text)
    return units / 1000 * size * (1.07 if bold else 1.0)


def _channels(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(hex_color: str) -> float:
    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _channels(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
