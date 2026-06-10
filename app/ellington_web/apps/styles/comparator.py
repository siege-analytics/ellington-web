"""Pure-Python style comparator. Frozen typed interface so:

  * sub-4 (audio pipeline) writes ``DetectedVoicing`` lists into ``critique_passage()``
  * sub-5 (LLM coach) reads ``CritiqueDraft.commentary_items[]`` to render prose

v0 is rule-based — no LLM. Operates on the catalog rows landed in sub-A,
soft-skips placeholder catalogs (they contribute nothing to the score
but don't crash). Once the plugin agent's distillation pass produces
real prescriptive content and sub-E's catalog-sync flips
``is_placeholder=False`` on rows, the same comparator code generates
substantively interesting commentary.

Style distance is the core primitive. Given two ``Style`` rows it
returns a ``DistanceProfile`` capturing shared tags, diverging tags,
signature alignment, and (if the target style authored one) a
``characteristic_quote_from_b`` — the verbatim "a bebop player would
say…" cross-style quote that sub-5 renders in the user's critique.

The product-level intent (per session 2026-06-10 morning):

    "I know you said you want to use Bossa Nova chords against a
     Gypsy Jazz background, but you're using some Ralph Patt style
     chromatic voicings, which is neat! A bebop player would say
     you're using bebop chords in bossa nova rhythm."

`critique_passage()` produces the structured pieces of that paragraph;
sub-5 stitches them into prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .models import (
    Critique,
    Master,
    Style,
    StylePreset,
    StyleSelection,
)


# ---------------------------------------------------------------------------
# Frozen typed signature: sub-4's audio pipeline and sub-D's smoke view both
# build these dataclasses and hand them in.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectedVoicing:
    """A single chord-voicing observation from the audio pipeline.

    sub-4 will produce one ``DetectedVoicing`` per recognized chord
    event. The smoke view (sub-D) hand-constructs them from a POST body.
    Shape is intentionally minimal — comparator works on the tags;
    everything else is provenance for the LLM coach.
    """

    chord_symbol: str
    """Detected chord symbol — e.g. 'Cmaj7', 'Dm7b5', 'G7alt'."""

    voicing_style_tags: tuple[str, ...] = ()
    """Tags carried by the voicing — drop-2, shell, chromatic, walking,
    etc. sub-4 derives these from the detected pitch set + the plugin's
    voicings.json catalog lookup."""

    confidence: float = 1.0
    """sub-4's confidence in the detection; 1.0 from the smoke view."""

    timestamp_ms: int | None = None
    """Optional position in the source audio. Used for time-localized
    feedback. sub-4 populates; smoke view leaves as None."""


@dataclass
class DistanceProfile:
    """Comparator's read on how far two styles diverge.

    Symmetric in ``shared_dimensions`` but asymmetric in
    ``characteristic_quote_from_b`` (which comes from style_b's
    authored ``divergence_notes`` against style_a — populated only
    when both are real, not placeholders).
    """

    shared_tags: frozenset[str]
    """Voicing-style tags both styles favour."""

    diverging_tags: frozenset[str]
    """Voicing-style tags one favours and the other doesn't."""

    signature_alignment: dict[str, str]
    """Per-signature-key alignment verdicts. Each entry is one of
    'aligned', 'divergent', 'unknown' (one or both styles unspecified)."""

    characteristic_quote_from_b: str | None = None
    """style_b's authored "a <style_b> player would say…" cross-style
    quote, when one exists against style_a's slug. Verbatim rendering
    target for sub-5."""

    placeholder_flag: bool = False
    """True when either style is placeholder — distance is structurally
    valid but content-wise meaningless. Caller decides whether to
    surface to users (smoke view: yes; production: filter out)."""


@dataclass
class CritiqueDraft:
    """Structured comparator output. ``Critique`` model wraps this.

    sub-5 reads ``commentary_items`` to compose user-facing prose.
    """

    selection_id: int
    style_match_score: float
    """0.0–1.0: how well the detected playing matches target_preset."""

    detected_axes: dict[str, dict[str, object]] = field(default_factory=dict)
    """Comparator's guess at what the user is ACTUALLY playing:
        { 'style': {'slug': 'cool-jazz', 'confidence': 0.61}, ... }
    Each axis is independent; missing axes mean no guess.
    """

    commentary_items: list[str] = field(default_factory=list)
    """Structured commentary fragments. sub-5 turns these into prose.

    Order matters — earlier items are 'top-line observation' (you played
    cool-jazz when you said bebop), later items are detail ("you used
    a Patt-style chromatic voicing on beat 3").
    """

    placeholder_warning: bool = False
    """True if any catalog row in the selection or detected axes is
    placeholder. Surfaces to the smoke view; sub-5 can render an honest
    'this is an early MVP, the styles aren't fully distilled yet' note.
    """


# ---------------------------------------------------------------------------
# Style distance primitive
# ---------------------------------------------------------------------------


def _tag_affinity_set(style: Style) -> frozenset[str]:
    """Extract the styles's voicing-style tag set from the affinity dict.
    Treats any tag with weight > 0 as 'favoured'.
    """
    affinity = style.voicing_style_tag_affinity or {}
    return frozenset(tag for tag, weight in affinity.items() if (weight or 0) > 0)


def _signature_alignment(
    sig_a: dict[str, object],
    sig_b: dict[str, object],
) -> dict[str, str]:
    """Per-key verdict on rhythmic / harmonic signature alignment.

    For each key present in EITHER side, classify as 'aligned' (same
    value), 'divergent' (different values), or 'unknown' (only one side
    has an opinion).
    """
    keys = (sig_a or {}).keys() | (sig_b or {}).keys()
    out: dict[str, str] = {}
    for key in keys:
        va = (sig_a or {}).get(key)
        vb = (sig_b or {}).get(key)
        if va is None or vb is None:
            out[key] = "unknown"
        elif va == vb:
            out[key] = "aligned"
        else:
            out[key] = "divergent"
    return out


def _quote_from_b_against_a(style_a: Style, style_b: Style) -> str | None:
    """Pull the verbatim characteristic quote style_b has authored
    against style_a's slug, if any.
    """
    notes = style_b.divergence_notes or []
    for note in notes:
        if isinstance(note, dict) and note.get("vs_style") == style_a.slug:
            quote = note.get("characteristic_quote")
            if isinstance(quote, str) and quote.strip():
                return quote.strip()
    return None


def style_distance(style_a: Style, style_b: Style) -> DistanceProfile:
    """Distance + commentary primitive between two ``Style`` rows.

    Symmetric in tag set comparisons; asymmetric in the
    ``characteristic_quote_from_b`` field (which depends on which
    style is doing the talking about which).
    """
    tags_a = _tag_affinity_set(style_a)
    tags_b = _tag_affinity_set(style_b)

    return DistanceProfile(
        shared_tags=tags_a & tags_b,
        diverging_tags=tags_a ^ tags_b,
        signature_alignment=_signature_alignment(
            (style_a.rhythmic_signature or {}) | (style_a.harmonic_signature or {}),
            (style_b.rhythmic_signature or {}) | (style_b.harmonic_signature or {}),
        ),
        characteristic_quote_from_b=_quote_from_b_against_a(style_a, style_b),
        placeholder_flag=bool(style_a.is_placeholder or style_b.is_placeholder),
    )


# ---------------------------------------------------------------------------
# Passage critique
# ---------------------------------------------------------------------------


def _passage_tag_set(passage: Iterable[DetectedVoicing]) -> frozenset[str]:
    """Union of voicing_style_tags across the passage's detected voicings."""
    out: set[str] = set()
    for v in passage:
        out.update(v.voicing_style_tags)
    return frozenset(out)


def _style_match_score(
    style: Style | None,
    passage_tags: frozenset[str],
) -> float:
    """Jaccard-ish: |passage ∩ style| / |passage ∪ style|. Returns 0.0
    when either side is empty (no signal). Caller maps None to neutral.
    """
    if style is None:
        return 0.0
    style_tags = _tag_affinity_set(style)
    if not style_tags or not passage_tags:
        return 0.0
    union = style_tags | passage_tags
    if not union:
        return 0.0
    return len(style_tags & passage_tags) / len(union)


def _guess_detected_axes(
    passage: Iterable[DetectedVoicing],
    candidate_styles: Sequence[Style],
) -> dict[str, dict[str, object]]:
    """Score every candidate Style against the passage and pick the
    highest-Jaccard non-zero match as the 'detected style' axis guess.

    Returns the structured detected_axes dict ready for Critique.
    Empty dict if no candidate scored above 0.
    """
    passage_tags = _passage_tag_set(passage)
    if not passage_tags:
        return {}

    scores: list[tuple[Style, float]] = [
        (s, _style_match_score(s, passage_tags)) for s in candidate_styles
    ]
    scores = [(s, sc) for s, sc in scores if sc > 0]
    if not scores:
        return {}

    scores.sort(key=lambda kv: kv[1], reverse=True)
    best_style, best_score = scores[0]
    return {
        "style": {"slug": best_style.slug, "confidence": round(best_score, 4)},
    }


def critique_passage(
    detected_voicings: Sequence[DetectedVoicing],
    selection: StyleSelection,
    *,
    candidate_styles: Sequence[Style] | None = None,
) -> CritiqueDraft:
    """End-to-end comparator entry point.

    Args:
        detected_voicings: ordered passage from sub-4 / smoke view.
        selection: the user's target × backing selection (FK chain into
            StylePreset → Master / Style / Idiom).
        candidate_styles: which Style rows to score against when
            guessing the user's actual style. Defaults to ALL Style rows
            in the DB; tests pass a narrower set.

    Returns:
        CritiqueDraft. Caller persists as a ``Critique`` row.
    """
    target_style = selection.target_preset.style
    backing_style = selection.backing_preset.style

    if candidate_styles is None:
        candidate_styles = list(Style.objects.all())

    passage_tags = _passage_tag_set(detected_voicings)
    match_score = _style_match_score(target_style, passage_tags)
    detected_axes = _guess_detected_axes(detected_voicings, candidate_styles)

    placeholder_warning = False
    for catalog_row in (
        target_style,
        backing_style,
        selection.target_preset.master,
        selection.target_preset.idiom,
        selection.backing_preset.master,
        selection.backing_preset.idiom,
    ):
        if catalog_row is not None and getattr(catalog_row, "is_placeholder", False):
            placeholder_warning = True
            break

    commentary_items: list[str] = []

    # Top-line: did the user play what they said they would?
    if target_style is not None:
        commentary_items.append(
            f"target:{target_style.slug}:match-score={round(match_score, 3)}"
        )
    detected_style_slug = (detected_axes.get("style") or {}).get("slug")
    if (
        target_style is not None
        and detected_style_slug
        and detected_style_slug != target_style.slug
    ):
        commentary_items.append(
            f"detected-divergence:said={target_style.slug}:played={detected_style_slug}"
        )

    # Cross-style quote: pull from the DETECTED style's divergence_notes
    # against the TARGET style. That's the "a bebop player would say…"
    # voice — bebop is the detected style; target is what the user said
    # they wanted. The quote is written from bebop's perspective.
    if (
        target_style is not None
        and detected_style_slug
        and detected_style_slug != target_style.slug
    ):
        detected_style_row = next(
            (s for s in candidate_styles if s.slug == detected_style_slug), None,
        )
        if detected_style_row is not None:
            distance = style_distance(target_style, detected_style_row)
            if distance.characteristic_quote_from_b:
                commentary_items.append(
                    f'characteristic-quote:from={detected_style_row.slug}:'
                    f'against={target_style.slug}:'
                    f'quote="{distance.characteristic_quote_from_b}"'
                )

    # Backing context: if the user's playing diverges from BOTH target
    # and backing styles, surface the triangle ("you said X over Y,
    # you're playing Z"). Important for the bossa-vs-gypsy-vs-bebop
    # example from the product brief.
    if (
        backing_style is not None
        and target_style is not None
        and detected_style_slug
        and detected_style_slug != target_style.slug
        and detected_style_slug != backing_style.slug
    ):
        commentary_items.append(
            f"triangle:target={target_style.slug}:"
            f"backing={backing_style.slug}:"
            f"detected={detected_style_slug}"
        )

    return CritiqueDraft(
        selection_id=selection.pk,
        style_match_score=match_score,
        detected_axes=detected_axes,
        commentary_items=commentary_items,
        placeholder_warning=placeholder_warning,
    )


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------


def persist_critique(draft: CritiqueDraft, *, audio_input_ref: str | None = None) -> Critique:
    """Materialize a CritiqueDraft as a ``Critique`` DB row. The smoke
    view and sub-4 both go through this so the persistence shape stays
    in one place.
    """
    return Critique.objects.create(
        selection_id=draft.selection_id,
        style_match_score=draft.style_match_score,
        detected_axes=draft.detected_axes,
        commentary="\n".join(draft.commentary_items),
        audio_input_ref=audio_input_ref,
    )
