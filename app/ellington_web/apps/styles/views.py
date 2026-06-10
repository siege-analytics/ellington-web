"""Smoke view for the comparator. Proves the end-to-end pipeline
works against seeded data before audio (sub-4) and the LLM coach
(sub-5) land.

Two endpoints:

  GET  /critique/preview/?demo=1      Canned demo against seed data
  POST /critique/preview/              JSON: { selection_id, voicings: [
                                            {chord_symbol, voicing_style_tags, ...}
                                       ] }
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .comparator import DetectedVoicing, critique_passage, persist_critique
from .models import Style, StylePreset, StyleSelection


User = get_user_model()


@csrf_exempt  # POST endpoint takes JSON; consumer is sub-4 + smoke test
@require_http_methods(["GET", "POST"])
def critique_preview(request: HttpRequest) -> JsonResponse:
    """Smoke endpoint for the comparator.

    GET ?demo=1 runs a canned bossa-target / gypsy-backing / bebop-played
    triangle against the seeded data. Useful for proving the architecture
    works without sub-4's audio pipeline.

    POST takes a JSON body:
        {
            "selection_id": int,        # required
            "voicings": [                # required, at least one entry
                {
                    "chord_symbol": str,
                    "voicing_style_tags": [str, ...],
                    "confidence": float?,
                    "timestamp_ms": int?
                },
                ...
            ],
            "persist": bool?,            # default False; if True, writes Critique row
            "audio_input_ref": str?      # only used when persist=True
        }
    """
    if request.method == "GET":
        if request.GET.get("demo") == "1":
            return _run_demo(persist=False)
        return JsonResponse(
            {
                "error": (
                    "GET requires ?demo=1; otherwise POST a JSON body with "
                    "selection_id + voicings. See docstring for shape."
                )
            },
            status=400,
        )

    # POST path
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return JsonResponse({"error": f"invalid JSON body: {exc}"}, status=400)

    selection_id = body.get("selection_id")
    raw_voicings = body.get("voicings") or []
    if not selection_id or not raw_voicings:
        return JsonResponse(
            {"error": "selection_id and voicings (non-empty) are required"},
            status=400,
        )

    selection = get_object_or_404(StyleSelection, pk=selection_id)
    voicings = [_voicing_from_dict(v) for v in raw_voicings]

    draft = critique_passage(voicings, selection)

    response = _draft_to_json(draft)

    if body.get("persist"):
        critique = persist_critique(draft, audio_input_ref=body.get("audio_input_ref"))
        response["persisted_critique_id"] = critique.pk

    return JsonResponse(response)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _voicing_from_dict(d: dict) -> DetectedVoicing:
    return DetectedVoicing(
        chord_symbol=str(d.get("chord_symbol", "")),
        voicing_style_tags=tuple(d.get("voicing_style_tags") or ()),
        confidence=float(d.get("confidence", 1.0)),
        timestamp_ms=d.get("timestamp_ms"),
    )


def _draft_to_json(draft) -> dict:
    return {
        "selection_id": draft.selection_id,
        "style_match_score": draft.style_match_score,
        "detected_axes": draft.detected_axes,
        "commentary_items": draft.commentary_items,
        "placeholder_warning": draft.placeholder_warning,
    }


def _run_demo(*, persist: bool) -> JsonResponse:
    """Build a canned bossa-target / gypsy-backing / bebop-played
    selection against seeded data and return the comparator's output.

    Requires seed_style_catalog has been run AND a demo user + presets
    exist (created lazily here). Idempotent — re-invoking the demo
    reuses the same selection.
    """
    bossa = Style.objects.filter(slug="bossa-nova").first()
    gypsy = Style.objects.filter(slug="gypsy-jazz").first()
    if bossa is None or gypsy is None:
        return JsonResponse(
            {
                "error": (
                    "demo requires seeded catalog — run "
                    "`manage.py seed_style_catalog` first"
                )
            },
            status=503,
        )

    demo_user, _ = User.objects.get_or_create(
        username="comparator-demo",
        defaults={"email": "demo@ellington.local"},
    )
    target_preset, _ = StylePreset.objects.get_or_create(
        slug="demo-target-bossa",
        defaults={"display_name": "Bossa Target (demo)", "style": bossa},
    )
    backing_preset, _ = StylePreset.objects.get_or_create(
        slug="demo-backing-gypsy",
        defaults={"display_name": "Gypsy Backing (demo)", "style": gypsy},
    )
    selection, _ = StyleSelection.objects.get_or_create(
        user=demo_user,
        target_preset=target_preset,
        backing_preset=backing_preset,
    )

    # Hard-coded "user played bebop chords" passage
    voicings = [
        DetectedVoicing(
            chord_symbol="Cmaj7",
            voicing_style_tags=("shell", "walking-bass", "chromatic"),
        ),
        DetectedVoicing(
            chord_symbol="Am7",
            voicing_style_tags=("shell", "chromatic"),
        ),
        DetectedVoicing(
            chord_symbol="Dm7",
            voicing_style_tags=("walking-bass", "shell"),
        ),
        DetectedVoicing(
            chord_symbol="G7",
            voicing_style_tags=("chromatic", "tritone-sub"),
        ),
    ]
    draft = critique_passage(voicings, selection)
    response = _draft_to_json(draft)
    response["demo"] = True
    response["demo_explanation"] = (
        "User selected bossa-nova target × gypsy-jazz backing but played "
        "shell+walking+chromatic voicings (bebop affinity). Comparator should "
        "detect bebop, render the bossa↔bebop characteristic quote, and "
        "emit triangle commentary."
    )

    if persist:
        critique = persist_critique(draft, audio_input_ref="demo:canned")
        response["persisted_critique_id"] = critique.pk

    return JsonResponse(response)
