# MuseJazz fonts (SIL OFL)

This directory is the destination for the MuseJazz Text + MuseJazz
Symbol typefaces used as the Ellington brand identity per
[ellington-web#102](https://github.com/siege-analytics/ellington-web/issues/102).

## Why MuseJazz

- **License is clean for web + email embed**: ships under SIL Open Font
  License 1.1 with the MuseScore distribution.
- **Lineage signal**: Ellington derives from the
  [musescore4-chord-library-plugin](https://github.com/siege-analytics/musescore4-chord-library-plugin)
  master-distillation pipeline; reusing the typeface acknowledges that
  lineage without claiming it explicitly.
- **Two-font family**: `MuseJazz Text` for prose / chord names /
  wordmark, `MuseJazz Symbol` for music glyphs. Keeps the practice UI
  typographically coherent.

## How to populate

1. Source the fonts from the MuseScore source tree
   [`MuseScore/fonts/MuseJazz/`](https://github.com/musescore/MuseScore/tree/master/fonts/MuseJazz)
   or your local MuseScore install at
   `/Applications/MuseScore 4.app/Contents/Resources/fonts/MuseJazz/`
   (macOS).
2. Convert the bundled TTF/OTF files to `woff2` + `woff` via
   [`fonttools`](https://fonttools.readthedocs.io/en/latest/) or
   [`font-converter`](https://everythingfonts.com/font-converter):

       fonttools ttLib.woff2 compress MuseJazzText.ttf
       # produces MuseJazzText.woff2

3. Copy the resulting files into this directory with the names
   referenced by `static/css/brand.css`:

   - `MuseJazzText.woff2`, `MuseJazzText.woff`
   - `MuseJazz.woff2`, `MuseJazz.woff`

4. Commit the `OFL.txt` license file alongside the binaries — the SIL
   OFL requires the license to ship with the font.

5. Run `python manage.py collectstatic --no-input` to pick up the new
   assets (Tekton sites-build-bake does this automatically in CI).

## Fallback stack

`static/css/brand.css` declares a fallback chain so the brand reads
correctly even before fonts are populated:

    var(--font-display) =
        "MuseJazz Text", "Bradley Hand", "Comic Sans MS", cursive, serif;

The Comic Sans entry is intentional — it's the closest universal
handwritten fallback for email clients that strip web fonts.
