# Ellington brand identity v1

Per [epic #96 sub-ticket (m)](https://github.com/siege-analytics/ellington-web/issues/96)
and [#102](https://github.com/siege-analytics/ellington-web/issues/102).

## Identity

**Ellington** is a practice and feedback web application for jazz
guitarists, derived from the
[musescore4-chord-library-plugin](https://github.com/siege-analytics/musescore4-chord-library-plugin)
master-distillation engine. The brand identity signals:

- **Practitioner-built, practitioner-facing** — a hand-copied lead-sheet
  feel, not a flashy consumer SaaS look.
- **Lineage to MuseScore** — typography reuse acknowledges the upstream
  without depending on it.
- **Pedagogy-coherent** — the brand palette IS the in-app chord-quality
  semantic palette. Every chord render reinforces brand recognition;
  every brand surface previews the pedagogy.

## Typography

**Primary typeface**: `MuseJazz Text` (SIL OFL, shipped with
MuseScore). Two-font family:

- `MuseJazz Text` — wordmark, prose, chord names
- `MuseJazz Symbol` — music notation glyphs in-app

**Fallback stack** (declared in
`static/css/brand.css` as `--font-display`):

    "MuseJazz Text", "Bradley Hand", "Comic Sans MS", cursive, serif

Comic Sans is intentional — it's the closest universally-available
handwritten fallback for email clients that strip web fonts.

**Body copy**: system-ui stack via `--font-body`. The display
typeface carries the brand personality; body copy stays readable.

## Color — chord-quality semantic palette

The palette doubles as the brand color system AND the in-app semantic
color for chord renders. One palette, two jobs.

| Quality | Hex | Meaning |
|---|---|---|
| `maj7` | `#c89f3c` | cream-gold — bright, open, warm consonance |
| `min7` | `#4a5f78` | slate-blue — cool, melancholic, stable |
| `dom7` | `#b76e2a` | mustard — tense, expectant, leading |
| `dim7` | `#5f1818` | oxblood — strong dissonance, tritone |
| `min7b5` | `#6e3a3a` | burgundy — half-diminished, leading-to |
| `alt` | `#8a3324` | rust — altered dominant, dense color |
| `sus` | `#6b7a4a` | olive — suspended, unresolved |
| `other` | `#6b5d44` | brown — fallback / uncategorized |

**Preference rendering** (engine-rule signed Likert per
[firing-spec v0.1](https://github.com/siege-analytics/musescore4-chord-library-plugin/blob/main/plugin/docs/engine-rules-firing-spec.md)):

| Preference | Color | Source |
|---|---|---|
| +2 strong recommend | `--chord-maj7` | warm side of the palette |
| +1 weak recommend | `--chord-dom7` | mustard, on-the-way |
| 0 neutral | `--fg-muted` | brown, restrained |
| -1 weak avoid | `--chord-min7b5` | burgundy, leading-to |
| -2 strong avoid | `--chord-dim7` | oxblood, dissonant |

## Surfaces

| Surface | Status | Notes |
|---|---|---|
| Wordmark SVG (light + dark) | shipped this PR | `static/img/brand/wordmark*.svg` |
| Favicon set | TODO | 16/32/180/512 — follow-up commit |
| App chrome (header, nav, admin) | TODO | Phase 6 sub-ticket TBD |
| Practice-session / chart views | TODO | #82, #98 — pulls from `brand.css` |
| Email `_base.html` | shipped in #104 | references the fallback stack |
| Sharing previews (OpenGraph) | TODO | sub-ticket (b) — dynamic per-Recording template |

## Files

- `static/css/brand.css` — palette + `@font-face` + utility classes
- `static/fonts/musejazz/` — destination for MuseJazz binaries
  (follow-up PR — see directory README)
- `static/fonts/musejazz/README.md` — provenance + populate-from-source
  instructions
- `static/img/brand/wordmark.svg` — light wordmark
- `static/img/brand/wordmark-dark.svg` — dark wordmark
- `apps/core/templates/email/_base.html` — uses the fallback stack
  (shipped in #104)

## License audit

- **MuseJazz**: SIL Open Font License 1.1. Web embed and redistribution
  permitted. `OFL.txt` ships alongside the binaries in
  `static/fonts/musejazz/` once the font fetch lands.
- **No third-party imagery** — wordmark is text-only. No likenesses, no
  photos, no estate-encumbered material.

## Out of scope

- Full component library / design system tokens (separate ticket)
- Marketing site landing copy
- Logo animation / video
- Marketing-side merch
