"""Voicing lookup — best-effort match from EngineRule to Voicing rows (#286).

The rule_review UI needs to render fretboard diagrams inside the
pedagogue confirmation form so pedagogues can actually see what
they're confirming. This module owns the matching logic between
an EngineRule and the candidate Voicing rows that could be the
"voicing recommendation" the rule is talking about.

Match strategy is deliberately broad-to-narrow:

1. Filter by chord quality — the rule's ``quality_binding`` (a list
   like ``["dom7", "dom7b9"]``) intersects ``Voicing.chord_quality``.
2. If ``then_action.voicing_family`` is present, prefer voicings
   whose ``category`` matches (voicing_family maps to category).
3. Order results 6-string first (standard guitar), lower fret_number
   first (open positions are easier for a pedagogue to eyeball).

Falls back to ``Voicing.objects.none()`` when the rule carries no
quality binding — we prefer a clean empty state to a false match.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Case, IntegerField, Q, QuerySet, When

from apps.voicings.models import Voicing

if TYPE_CHECKING:
    from apps.engine_rules.models import EngineRule


def resolve_voicings_for_rule(rule: "EngineRule") -> QuerySet[Voicing]:
    """Return candidate voicings for one rule, best-match first.

    Contract:
    - Empty ``quality_binding`` → empty queryset.
    - Multiple qualities on rule → OR'd match against Voicing.
    - ``then_action.voicing_family`` (if present) is a category hint,
      not a hard filter — voicings with matching category sort first.
    - Order: category-match desc, strings=6 first, fret_number asc,
      voicing_id ascending as stable tiebreaker.
    """
    qualities = list(rule.quality_binding or [])
    if not qualities:
        return Voicing.objects.none()

    # Case-insensitive quality match — plugin schema is free-text
    # so we normalize both sides.
    quality_filter = Q()
    for q in qualities:
        quality_filter |= Q(chord_quality__iexact=q)

    qs = Voicing.objects.filter(quality_filter, is_active=True)

    then_action = rule.then_action or {}
    family = then_action.get("voicing_family") or then_action.get(
        "voicing_category"
    ) or then_action.get("voicing_shape")

    if family:
        # Boost matching-category rows to the top; do NOT filter them
        # out — a rule that names family "shell" may still be
        # correctly confirmed against a "drop2" voicing if the
        # pedagogue disagrees with the family classification.
        qs = qs.annotate(
            _family_match=Case(
                When(category__iexact=family, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("_family_match", "-strings", "fret_number", "voicing_id")
        # ``-strings`` sorts 7 before 6; we want 6 first (standard
        # guitar). Fix with an explicit annotation.
        qs = qs.annotate(
            _strings_match=Case(
                When(strings=6, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by(
            "_family_match", "_strings_match", "fret_number", "voicing_id",
        )
    else:
        qs = qs.annotate(
            _strings_match=Case(
                When(strings=6, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("_strings_match", "fret_number", "voicing_id")

    return qs


__all__ = ["resolve_voicings_for_rule"]
