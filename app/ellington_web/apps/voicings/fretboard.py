"""Pure-function fretboard SVG renderer (#186 Phase 2).

Reads a :class:`apps.voicings.models.Voicing`'s geometry and emits an
inline SVG string. Server-rendered so the page works with JS off
and so search engines / cached HTML carry the diagrams.

Phase 2 ships the minimum-viable render: strings as vertical lines,
visible frets as horizontal lines, fingered dots as filled circles,
mutes as ``×`` glyphs above the nut, open strings as ``○`` glyphs.
Phase 2b will add fingering numbers and chord-tone coloring.

The geometry follows the plugin's QML convention:
- ``string`` 1 = highest pitch (rightmost in a right-handed render)
- ``fret`` 1 = topmost visible fret (i.e. ``fret_number``)
- ``visible_frets`` is the row count of the diagram window
"""

from __future__ import annotations

from typing import Iterable, Mapping


def render_svg(
    *,
    strings: int,
    fret_number: int,
    visible_frets: int,
    dots: Iterable[Mapping[str, int]],
    mutes: Iterable[int] = (),
    open_strings: Iterable[int] = (),
    width: int = 160,
    height: int = 200,
) -> str:
    """Return an inline SVG string for one voicing diagram.

    Args mirror the model fields (see ``Voicing.dots``, ``Voicing.mutes``,
    ``Voicing.open_strings``). ``strings`` is the instrument string
    count (6 or 7 typically). ``visible_frets`` is the row count of
    the diagram window.
    """
    if strings < 2 or visible_frets < 1:
        return ""

    pad_x, pad_y = 16, 24
    inner_w = width - 2 * pad_x
    inner_h = height - 2 * pad_y
    string_step = inner_w / (strings - 1)
    fret_step = inner_h / visible_frets

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'class="fretboard" role="img" '
        f'aria-label="fretboard diagram">',
    ]

    # Nut indicator (thick top line) when fret_number == 0.
    nut_y = pad_y
    if fret_number == 0:
        parts.append(
            f'<rect x="{pad_x - 1}" y="{nut_y - 3}" '
            f'width="{inner_w + 2}" height="3" fill="currentColor" />'
        )
    else:
        # Fret position label to the left of the top row
        parts.append(
            f'<text x="{pad_x - 6}" y="{nut_y + 4}" '
            f'text-anchor="end" font-size="9" fill="currentColor">'
            f'{fret_number}fr</text>'
        )

    # Vertical strings — string 1 is rightmost (high-pitch first)
    for s in range(strings):
        x = pad_x + s * string_step
        parts.append(
            f'<line x1="{x}" y1="{nut_y}" x2="{x}" '
            f'y2="{nut_y + inner_h}" stroke="currentColor" '
            f'stroke-width="1" />'
        )

    # Horizontal frets
    for f in range(visible_frets + 1):
        y = nut_y + f * fret_step
        parts.append(
            f'<line x1="{pad_x}" y1="{y}" x2="{pad_x + inner_w}" '
            f'y2="{y}" stroke="currentColor" stroke-width="1" />'
        )

    def string_x(string_num: int) -> float:
        # Plugin numbers strings 1..N from highest pitch.
        # Render high pitch on the right: string 1 -> rightmost.
        idx = strings - string_num
        return pad_x + idx * string_step

    # Mutes (×) and opens (○) above the nut
    glyph_y = nut_y - 8
    for s in mutes:
        if 1 <= s <= strings:
            parts.append(
                f'<text x="{string_x(s)}" y="{glyph_y}" '
                f'text-anchor="middle" font-size="11" '
                f'fill="currentColor">×</text>'
            )
    for s in open_strings:
        if 1 <= s <= strings:
            parts.append(
                f'<circle cx="{string_x(s)}" cy="{glyph_y - 3}" '
                f'r="4" fill="none" stroke="currentColor" '
                f'stroke-width="1" />'
            )

    # Fingered dots
    for dot in dots:
        s = dot.get("string")
        f = dot.get("fret")
        if s is None or f is None:
            continue
        if not (1 <= s <= strings) or not (1 <= f <= visible_frets):
            continue
        cx = string_x(s)
        cy = nut_y + (f - 0.5) * fret_step
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="6" '
            f'fill="currentColor" />'
        )

    parts.append("</svg>")
    return "".join(parts)
