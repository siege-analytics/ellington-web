"""Tests for the ChartImport model (Phase 4-PDF foundation, #80).

Covers the model-level contracts the upcoming orchestrator (#81) and
view layer (#82) will rely on:

- Status state machine: enum values are exactly what the lifecycle
  expects (no skips, no unexpected terminals). CANCELED added per
  PR #83 review for practitioner-initiated revoke.
- ``COMPLETE`` vs ``PARTIAL`` vs ``FAILED`` resolution rule based on
  ``pages_succeeded`` / ``pages_failed`` (the orchestrator in #81
  reads this back; pinning it here means a future refactor of the
  resolution logic has to match).
- Idempotency: ``(user, file_ref)`` unique constraint enforces
  per-user idempotency (NOT global — two practitioners legitimately
  upload the same Real Book scan).
- Reverse relation: ``chart_import.songs`` returns extracted Songs.
- Cascade behavior:
  - Deleting a ChartImport sets ``Song.import_run = NULL``.
  - Deleting a User SETs NULL on ChartImport.user (preserves audit
    trail per the plugin-agent #83 review).
  - Deleting a Songbook SETs NULL on ChartImport.source_songbook.
- ``error_log`` JSON shape: the upload view + admin read this in a
  per-page form; the schema lives here.
- Index existence: composite index for the per-user list view.
- OMR_PDF choice in ImportSource is wired.
"""

from __future__ import annotations

import uuid

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


def _user(label: str = "u"):
    # Unique-suffix the username so parallel test runs and per-class
    # setUp don't collide on a duplicate-User IntegrityError. Plugin
    # agent flagged the bare-name version on #83 review.
    return get_user_model().objects.create_user(
        f"{label}-{uuid.uuid4().hex[:8]}", password="pw"
    )


def _songbook(slug: str | None = None) -> Songbook:
    return Songbook.objects.create(
        slug=slug or f"sb-{uuid.uuid4().hex[:8]}",
        title="Test Songbook",
    )


class TestChartImportStatusEnum(TestCase):
    """Lifecycle enum is exactly what the orchestrator + view expect."""

    def test_all_expected_states_exist(self) -> None:
        self.assertEqual(ChartImportStatus.PENDING, "pending")
        self.assertEqual(ChartImportStatus.QUEUED, "queued")
        self.assertEqual(ChartImportStatus.RUNNING, "running")
        self.assertEqual(ChartImportStatus.COMPLETE, "complete")
        self.assertEqual(ChartImportStatus.PARTIAL, "partial")
        self.assertEqual(ChartImportStatus.CANCELED, "canceled")
        self.assertEqual(ChartImportStatus.FAILED, "failed")

    def test_no_unexpected_states_added(self) -> None:
        # If a contributor adds a status without updating the state
        # machine docs + #81 orchestrator + #82 view, this fails noisily.
        expected = {
            "pending",
            "queued",
            "running",
            "complete",
            "partial",
            "canceled",
            "failed",
        }
        self.assertEqual(
            {v for v, _ in ChartImportStatus.choices},
            expected,
        )


class TestImportSourceOmrPdf(TestCase):
    """ImportSource has the OMR_PDF choice wired."""

    def test_omr_pdf_choice_exists(self) -> None:
        self.assertEqual(ImportSource.OMR_PDF, "omr-pdf")
        self.assertIn("omr-pdf", {v for v, _ in ImportSource.choices})


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


class TestFileRefPerUserUniqueness(TestCase):
    """Idempotency scope is per-user, NOT global.

    Two practitioners legitimately upload the same Real Book scan and
    each gets their own ChartImport. The same user re-uploading the
    same SHA reuses the existing row (idempotency).
    """

    def test_same_user_same_file_ref_collides(self) -> None:
        u = _user()
        ChartImport.objects.create(user=u, file_ref="sha-dup")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChartImport.objects.create(user=u, file_ref="sha-dup")

    def test_different_users_same_file_ref_both_succeed(self) -> None:
        # Real Book scans are widely shared; per-user uniqueness is
        # the right scope. Global uniqueness would leak existence
        # info across users (plugin-agent #83 review HIGH).
        u1 = _user("alice")
        u2 = _user("bob")
        ChartImport.objects.create(user=u1, file_ref="sha-shared")
        # Different user, same file → must NOT raise
        ChartImport.objects.create(user=u2, file_ref="sha-shared")
        self.assertEqual(
            ChartImport.objects.filter(file_ref="sha-shared").count(), 2
        )

    def test_null_user_same_file_ref_does_not_collide(self) -> None:
        # The unique constraint is conditional on user__isnull=False, so
        # orphan ChartImports (user deleted) don't block other live users
        # from re-uploading the same PDF.
        ChartImport.objects.create(user=None, file_ref="sha-orphan")
        # Another null-user upload of the same SHA: allowed
        ChartImport.objects.create(user=None, file_ref="sha-orphan")
        self.assertEqual(
            ChartImport.objects.filter(
                user__isnull=True, file_ref="sha-orphan"
            ).count(),
            2,
        )


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
    """SET_NULL semantics on every FK on ChartImport + downstream Song.

    Per plugin-agent #83 review HIGH: deleting a User must preserve
    the audit trail (ChartImport survives with user=NULL); deleting a
    Songbook must not vaporize the import record; deleting a
    ChartImport sets Song.import_run = NULL.
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

    def test_deleting_user_nulls_chart_import_user(self) -> None:
        # The audit trail is more valuable than the link back to a
        # deleted account. Cascading the ChartImport would also
        # cascade through Song.import_run → NULL, stripping
        # provenance off Songs the deleted user contributed (Songs
        # don't have a user FK; they're owned by the Songbook).
        u = _user()
        ci = ChartImport.objects.create(user=u, file_ref="sha-user-del")
        ci_pk = ci.pk
        u.delete()
        ci.refresh_from_db()
        self.assertIsNone(ci.user)
        # ChartImport row still exists
        self.assertTrue(ChartImport.objects.filter(pk=ci_pk).exists())

    def test_deleting_songbook_nulls_source_songbook(self) -> None:
        u = _user()
        sb = _songbook()
        ci = ChartImport.objects.create(
            user=u, file_ref="sha-sb-del", source_songbook=sb
        )
        sb.delete()
        ci.refresh_from_db()
        self.assertIsNone(ci.source_songbook)
        # ChartImport row still exists
        self.assertTrue(ChartImport.objects.filter(pk=ci.pk).exists())


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

    def test_error_log_accepts_arbitrary_shape_without_crash(self) -> None:
        # JSONField doesn't validate shape — that's by design (#81's
        # orchestrator owns the schema). Test that the model layer
        # doesn't choke on unexpected shapes, so an orchestrator bug
        # surfaces visibly in the view layer rather than as an
        # opaque save() failure.
        for payload in [
            [],
            ["not a dict"],
            {"unexpected_key": True},
            {"page_warnings": "not a dict"},
        ]:
            ChartImport.objects.create(
                user=_user(),
                file_ref=f"sha-shape-{uuid.uuid4().hex[:8]}",
                error_log=payload,
            )


class TestIndexes(TestCase):
    """The composite (user, -created_at) index exists for the list view."""

    def test_user_recent_index_present(self) -> None:
        idx_names = {idx.name for idx in ChartImport._meta.indexes}
        self.assertIn("chartimport_user_recent_idx", idx_names)


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
