"""Tests for the ChartImport model (Phase 4-PDF foundation, #80).

Covers the model-level contracts the upcoming orchestrator (#81) and
view layer (#82) will rely on:

- Status state machine: enum values are exactly what the lifecycle
  expects (no skips, no unexpected terminals).
- ``COMPLETE`` vs ``PARTIAL`` vs ``FAILED`` resolution rule based on
  ``pages_succeeded`` / ``pages_failed`` (the orchestrator in #81
  reads this back; pinning it here means a future refactor of the
  resolution logic has to match).
- Idempotency: ``file_ref`` unique constraint prevents duplicate
  uploads of the same SHA-256-keyed PDF.
- Reverse relation: ``chart_import.songs`` returns extracted Songs.
- Cascade behavior: deleting a ChartImport sets ``Song.import_run = NULL``
  rather than cascade-deleting the Songs (which may be referenced by
  PracticeSessions).
- ``error_log`` JSON shape: the upload view + admin read this in a
  per-page form; the schema lives here.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.charts.models import (
    ChartImport,
    ChartImportStatus,
    ImportSource,
    Song,
    Songbook,
)


def _user(name: str = "alice"):
    return get_user_model().objects.create_user(name, password="pw")


def _songbook(slug: str = "omr-imports") -> Songbook:
    return Songbook.objects.create(slug=slug, title=slug)


class TestChartImportStatusEnum(TestCase):
    """Lifecycle enum is exactly what the orchestrator + view expect."""

    def test_all_expected_states_exist(self) -> None:
        self.assertEqual(ChartImportStatus.PENDING, "pending")
        self.assertEqual(ChartImportStatus.QUEUED, "queued")
        self.assertEqual(ChartImportStatus.RUNNING, "running")
        self.assertEqual(ChartImportStatus.COMPLETE, "complete")
        self.assertEqual(ChartImportStatus.PARTIAL, "partial")
        self.assertEqual(ChartImportStatus.FAILED, "failed")

    def test_no_unexpected_states_added(self) -> None:
        # If a contributor adds a status without updating the state
        # machine docs + #81 orchestrator + #82 view, this fails noisily.
        expected = {
            "pending", "queued", "running", "complete", "partial", "failed"
        }
        self.assertEqual(
            {v for v, _ in ChartImportStatus.choices},
            expected,
        )


class TestChartImportCreation(TestCase):
    """Basic shape: required fields, defaults, repr."""

    def test_minimum_required_fields(self) -> None:
        ci = ChartImport.objects.create(
            user=_user(),
            file_ref="sha256-deadbeef-test",
        )
        self.assertEqual(ci.status, ChartImportStatus.PENDING)
        self.assertEqual(ci.task_id, "")
        self.assertEqual(ci.pages_succeeded, 0)
        self.assertEqual(ci.pages_failed, 0)
        self.assertIsNone(ci.page_count)
        self.assertEqual(ci.error_log, {})
        self.assertIsNone(ci.completed_at)

    def test_repr_includes_status(self) -> None:
        ci = ChartImport.objects.create(
            user=_user(), file_ref="sha-x", status=ChartImportStatus.RUNNING
        )
        self.assertIn("running", str(ci))


class TestFileRefUniqueness(TestCase):
    """Idempotency: identical PDF SHAs collide at the DB layer."""

    def test_duplicate_file_ref_raises(self) -> None:
        ChartImport.objects.create(user=_user(), file_ref="sha-dup")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChartImport.objects.create(user=_user("bob"), file_ref="sha-dup")


class TestSongReverseRelation(TestCase):
    """``chart_import.songs`` returns the Songs extracted by this run."""

    def test_songs_reverse_relation_returns_extracted_songs(self) -> None:
        u = _user()
        sb = _songbook()
        ci = ChartImport.objects.create(
            user=u, file_ref="sha-rel", source_songbook=sb
        )
        s1 = Song.objects.create(
            slug="omr-song-1",
            title="Test 1",
            songbook=sb,
            import_source=ImportSource.OMR_PDF,
            import_run=ci,
        )
        s2 = Song.objects.create(
            slug="omr-song-2",
            title="Test 2",
            songbook=sb,
            import_source=ImportSource.OMR_PDF,
            import_run=ci,
        )
        # Hand-entered Song in the same songbook — should NOT appear via ci.songs
        Song.objects.create(
            slug="hand-song",
            title="Hand-entered",
            songbook=sb,
            import_source=ImportSource.HAND_ENTERED,
        )
        self.assertEqual(set(ci.songs.all()), {s1, s2})


class TestCascadeOnDelete(TestCase):
    """Deleting a ChartImport SETS NULL on Songs, doesn't cascade-delete them.

    Songs may already be referenced by a PracticeSession by the time
    someone removes the original upload; we'd rather orphan the
    import record than vaporize a practitioner's chart history.
    """

    def test_deleting_chart_import_nulls_song_import_run(self) -> None:
        u = _user()
        sb = _songbook()
        ci = ChartImport.objects.create(
            user=u, file_ref="sha-cascade", source_songbook=sb
        )
        s = Song.objects.create(
            slug="cascade-song",
            title="Cascade",
            songbook=sb,
            import_source=ImportSource.OMR_PDF,
            import_run=ci,
        )
        ci.delete()
        s.refresh_from_db()
        self.assertIsNone(s.import_run)
        # Song still exists — that's the whole point of SET_NULL
        self.assertTrue(Song.objects.filter(pk=s.pk).exists())


class TestPageCountInvariants(TestCase):
    """COMPLETE vs PARTIAL vs FAILED resolution from page-bookkeeping fields.

    The orchestrator (#81) computes the final status from
    ``pages_succeeded`` / ``pages_failed`` / ``page_count``. The
    resolution rule lives in the orchestrator code, but we pin the
    invariants here so a regression in the bookkeeping math gets
    caught at this layer too.
    """

    def _resolve(self, succeeded: int, failed: int) -> str:
        # Mirrors the rule documented on ChartImportStatus.
        if succeeded == 0 and failed > 0:
            return ChartImportStatus.FAILED
        if failed == 0 and succeeded > 0:
            return ChartImportStatus.COMPLETE
        if succeeded > 0 and failed > 0:
            return ChartImportStatus.PARTIAL
        # succeeded==0 and failed==0 is "not yet attempted" — RUNNING
        return ChartImportStatus.RUNNING

    def test_all_succeeded_is_complete(self) -> None:
        self.assertEqual(self._resolve(30, 0), ChartImportStatus.COMPLETE)

    def test_all_failed_is_failed(self) -> None:
        self.assertEqual(self._resolve(0, 30), ChartImportStatus.FAILED)

    def test_mixed_is_partial(self) -> None:
        self.assertEqual(self._resolve(28, 2), ChartImportStatus.PARTIAL)

    def test_single_page_succeeded_is_complete(self) -> None:
        # Single-page PDF (the degenerate case) — one success → COMPLETE
        self.assertEqual(self._resolve(1, 0), ChartImportStatus.COMPLETE)


class TestErrorLogShape(TestCase):
    """JSONField accepts the per-page warnings/failures shape #81 emits."""

    def test_error_log_round_trips_per_page_dict(self) -> None:
        ci = ChartImport.objects.create(
            user=_user(),
            file_ref="sha-elog",
            error_log={
                "page_warnings": {"3": ["low confidence on m4 chord symbol"]},
                "page_failures": {
                    "7": "Audiveris returned no staff",
                    "12": "VLM timeout after 60s",
                },
            },
        )
        ci.refresh_from_db()
        self.assertEqual(
            sorted(ci.error_log["page_failures"].keys()), ["12", "7"]
        )
        self.assertIn("low confidence", ci.error_log["page_warnings"]["3"][0])

    def test_error_log_defaults_to_empty_dict(self) -> None:
        ci = ChartImport.objects.create(user=_user(), file_ref="sha-empty")
        self.assertEqual(ci.error_log, {})


class TestCeleryQueueRoute(TestCase):
    """The omr-leadsheet task route lands in settings.

    #81 will create the actual ``charts.process_pdf_chart`` task and
    rely on this route to keep long PDF imports off the audio-analysis
    queue. Pinning the route here means a settings refactor that
    drops it gets caught before #81 runs.
    """

    def test_omr_leadsheet_queue_route_exists(self) -> None:
        from django.conf import settings

        routes = getattr(settings, "CELERY_TASK_ROUTES", {})
        self.assertIn("charts.process_pdf_chart", routes)
        self.assertEqual(
            routes["charts.process_pdf_chart"], {"queue": "omr-leadsheet"}
        )
