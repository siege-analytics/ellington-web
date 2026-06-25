"""analyze_recording — end-to-end audio analysis Celery task (#250).

When a Recording exists with both a user audio file (file_ref) and a
canonical BackingTrack (audio_ref), this task runs:

1. Time-alignment of user audio vs. canonical backing (#241)
2. Pitch extraction on user audio (#242)
3. Slice iteration via slicer.slices_for_song (PR #181)
4. Per-slice SliceObservation construction
5. Firing engine fire_all → RuleFireResult list
6. comparator.compare_slice → list[RuleVerdict]
7. Persist as AudioVerdict rows on the Recording

Recording.analysis_status advances PENDING → QUEUED → RUNNING →
COMPLETE / FAILED through the lifecycle.

Per child #250 of #232.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Iterable

from celery import shared_task
from django.utils import timezone


log = logging.getLogger(__name__)


# Pulled out so tests can patch the slice iterator without exercising
# the real slicer. Real implementation lives in apps.engine_rules.slicer
# (PR #181, currently in flight). Until that PR merges, this stub yields
# a single "whole-song" placeholder slice so the task is testable
# end-to-end without a slicer dependency. When #181 merges, swap the
# inner block to call ``apps.engine_rules.slicer.slices_for_song(song)``.
#
# Stub-with-inline-justification per the cross-cutting contract pattern:
# defer here cleanly, downstream swap is one-line, no other code paths
# branch on this stub.
def iter_slices_for_song(song):
    """Yield slice dicts with id + time_start_s + time_end_s.

    Stub until PR #181 lands. Yields a single placeholder slice covering
    the entire song time range so the analyze_recording task can be
    tested + run end-to-end. Replace inner body with
    ``from apps.engine_rules.slicer import slices_for_song;
    yield from slices_for_song(song)`` when #181 merges.
    """
    yield {
        "slice_id": f"{song.slug}-whole",
        "time_start_s": 0.0,
        "time_end_s": None,  # Run to end of recording
        "target_chord_canonical": "",
    }


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def analyze_recording(self, recording_id: int) -> int:
    """End-to-end audio analysis for one Recording.

    Returns the count of AudioVerdict rows created.
    """
    from apps.audio.alignment import align_recording
    from apps.audio.comparator import compare_slice
    from apps.audio.contract import (
        PlayedPitch, SliceObservation,
    )
    from apps.audio.models import AudioVerdict, PolarityChoice
    from apps.audio.pitch import extract_pitch_trace
    from apps.audio.storage import absolute_path_for as backing_path_for
    from apps.engine_rules.firing import Slice, fire_all, normalize_quality_token
    from apps.engine_rules.models import EngineRule
    from apps.practice.models import AnalysisStatus, Recording
    from apps.practice.storage import absolute_path_for as user_path_for

    recording = Recording.objects.select_related("session__song").get(pk=recording_id)
    backing = recording.session.backing_track if recording.session else None

    if recording.session is None or recording.session.song is None or backing is None:
        recording.analysis_status = AnalysisStatus.FAILED
        recording.notes = (
            (recording.notes or "")
            + "\nanalyze_recording: missing session/song/backing"
        )
        recording.save(update_fields=["analysis_status", "notes"])
        return 0

    recording.analysis_status = AnalysisStatus.RUNNING
    recording.save(update_fields=["analysis_status"])

    try:
        user_path = user_path_for(recording.file_ref)
        canon_path = backing_path_for(backing.audio_ref)

        alignment = align_recording(user_path, canon_path)
        pitch_trace = extract_pitch_trace(Path(user_path))

        song = recording.session.song
        rules = list(
            EngineRule.objects.filter(
                is_active=True, master__slug=song.songbook.slug if song.songbook else "",
            )
        ) if song else []
        rule_dicts = [_rule_to_dict(r) for r in rules]

        verdict_count = 0
        for slice_spec in iter_slices_for_song(song):
            obs = _build_slice_observation(
                slice_spec=slice_spec,
                pitch_trace=pitch_trace,
                alignment_confidence=alignment.confidence,
            )

            rule_fires = fire_all(
                rule_dicts,
                _slice_from_spec(slice_spec, PlayedPitch, Slice),
            )
            verdicts = compare_slice(rule_fires, obs)

            for v in verdicts:
                AudioVerdict.objects.update_or_create(
                    recording=recording,
                    slice_id=v.slice_id,
                    rule_id=v.rule_id,
                    defaults={
                        "rule_polarity": v.rule_polarity,
                        "verdict": v.verdict,
                        "evidence_type": v.evidence.type,
                        "evidence_payload": dataclasses.asdict(v.evidence),
                        "verdict_confidence": v.verdict_confidence,
                        "rule_evaluability_confidence":
                            v.rule_evaluability_confidence,
                    },
                )
                verdict_count += 1

        recording.analysis_status = AnalysisStatus.COMPLETE
        recording.analysis_completed_at = timezone.now()
        recording.save(
            update_fields=["analysis_status", "analysis_completed_at"],
        )
        return verdict_count

    except Exception as exc:
        log.exception("analyze_recording failed for %s", recording_id)
        recording.analysis_status = AnalysisStatus.FAILED
        recording.notes = (
            (recording.notes or "") + f"\nanalyze_recording: {exc!r}"
        )
        recording.save(update_fields=["analysis_status", "notes"])
        raise


def _rule_to_dict(rule) -> dict:
    """Translate an EngineRule row to the dict shape fire_all expects."""
    return {
        "rule_id": rule.rule_id,
        "preference": rule.preference,
        "polarity": rule.polarity,
        "quality_binding": list(rule.quality_binding or []),
        "applicability_reasons": list(rule.applicability_reasons or []),
        "when": rule.when_predicate or {},
        "then": rule.then_action or {},
        "anchor": rule.anchor or "",
        "source_page": rule.source_page,
    }


def _build_slice_observation(
    *,
    slice_spec: dict,
    pitch_trace,
    alignment_confidence: float,
):
    """Build a SliceObservation from a slice spec + the pitch trace.

    v0.1 fills only the fields the v0.1 comparator reads:
    matched_chord_tones / total_chord_tones / off_chord_tones /
    scale_drift_semitones / confidences. Chord-tone derivation is
    placeholder until the slicer (#181) supplies a target_chord
    canonical token; until then, we report 0/0 and let the comparator
    handle it via DeferredEvidence or low confidence.
    """
    from apps.audio.contract import SliceObservation
    import numpy as np

    # Pitch frames within the slice's time window
    end = slice_spec.get("time_end_s") or float(pitch_trace.times[-1] if len(pitch_trace.times) else 0)
    start = slice_spec.get("time_start_s") or 0.0
    mask = (pitch_trace.times >= start) & (pitch_trace.times <= end)
    voiced_in_window = pitch_trace.voicing_flag[mask] if hasattr(pitch_trace, "voicing_flag") else None
    freqs_in_window = pitch_trace.frequencies[mask] if hasattr(pitch_trace, "frequencies") else None

    if (
        freqs_in_window is None or len(freqs_in_window) == 0
        or voiced_in_window is None or not bool(np.any(voiced_in_window))
    ):
        pitch_conf = 0.0
    else:
        voiced_count = int(np.sum(voiced_in_window))
        total_count = int(len(voiced_in_window))
        pitch_conf = voiced_count / max(total_count, 1)

    composite = float(alignment_confidence) * float(pitch_conf)

    return SliceObservation(
        slice_id=slice_spec["slice_id"],
        matched_chord_tones=0,
        total_chord_tones=0,
        scale_drift_semitones=0.0,
        alignment_confidence=float(alignment_confidence),
        pitch_extraction_confidence=float(pitch_conf),
        observation_confidence=composite,
    )


def _slice_from_spec(slice_spec, PlayedPitch_cls, Slice_cls):
    """Build the firing-engine Slice from the slice_spec dict."""
    return Slice_cls(
        target_chord_canonical=slice_spec.get("target_chord_canonical") or "",
        prev_chord_canonical="",
        next_chord_canonical="",
        melody_note=None,
        key="",
        section_label="",
        beat_in_measure=1,
        time_signature="4/4",
        arrangement_style="",
        progression_type="",
        progression_position="",
        scale_context=None,
        harmonic_context=None,
    )


__all__ = ["analyze_recording", "iter_slices_for_song"]
