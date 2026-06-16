"""Tests for the Phase 4-PDF orchestrator (#81).

Covers the Celery task lifecycle and the dispatch helper. Mocks
``run_one_pdf`` so the test runner doesn't need omr-leadsheet's
system dependencies (Audiveris JVM, MuseScore, Tesseract) installed.

The actual omr-leadsheet pipeline is exercised by the
``tests/test_*_e2e.py`` files in the omr-leadsheet repo itself; here
we're testing Ellington's *integration shape* with it — same pattern
as #67/#69's tests of the placeholder analyzer.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.charts.models import (
    ChartImport,
    ChartImportStatus,
    ImportSource,
    Song,
    Songbook,
)
from apps.charts.omr import (
    OmrLeadsheetNotInstalled,
    OmrOutcome,
    OmrPipelineFailure,
)
from apps.charts.tasks import (
    dispatch_pdf_chart,
    process_pdf_chart,
)


def _user(label: str = "alice"):
    import uuid

    return get_user_model().objects.create_user(
        f"{label}-{uuid.uuid4().hex[:8]}", password="pw"
    )


def _songbook(slug: str | None = None) -> Songbook:
    import uuid

    return Songbook.objects.create(
        slug=slug or f"sb-{uuid.uuid4().hex[:8]}",
        title="OMR fixture",
    )


def _chart_import(
    *,
    songbook: Songbook | None = None,
    file_ref: str = "pdf_upload/sha-test.pdf",
) -> ChartImport:
    return ChartImport.objects.create(
        user=_user(),
        file_ref=file_ref,
        source_songbook=songbook,
    )


def _make_pdf_file(media_root: Path, file_ref: str) -> Path:
    """Create a placeholder file at MEDIA_ROOT/<file_ref>.

    The orchestrator's PDF-existence check uses ``is_file()``; the
    contents don't matter since ``run_one_pdf`` is mocked.
    """
    full = media_root / file_ref
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"%PDF-1.4 fixture")
    return full


def _make_mscz_file(workspace_dir: Path, stem: str = "fixture") -> Path:
    """Stage a .mscz path the importer mock can return.

    The musescore parser is mocked separately so the file contents
    don't matter — only the path needs to exist on disk for the
    orchestrator's success-path bookkeeping to make sense.
    """
    out_dir = workspace_dir / "lead_sheets" / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    mscz = out_dir / f"{stem}.mscz"
    mscz.write_bytes(b"fake mscz")
    return mscz


@override_settings(MEDIA_ROOT="/tmp/ellington-test-media-81")
class TestProcessPdfChartHappyPath(TestCase):
    """Successful end-to-end: PDF on disk → mocked omr-leadsheet → Songs imported."""

    def setUp(self) -> None:
        self.media_root = Path("/tmp/ellington-test-media-81")
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.songbook = _songbook()
        self.chart_import = _chart_import(
            songbook=self.songbook,
            file_ref="pdf_upload/sha-happy.pdf",
        )
        _make_pdf_file(self.media_root, self.chart_import.file_ref)

    def test_running_then_complete(self) -> None:
        workspace = self.media_root / "ws-happy"
        mscz = _make_mscz_file(workspace)
        with mock.patch(
            "apps.charts.tasks.run_one_pdf",
            return_value=OmrOutcome(mscz_path=mscz),
        ):
            with mock.patch(
                "apps.charts.tasks._workspace_dir",
                return_value=workspace,
            ):
                # Stub the ingest hop so we don't need a real .mscz.
                with mock.patch("apps.charts.tasks.parse_path") as parse_mock:
                    parse_mock.return_value = []
                    with mock.patch(
                        "apps.charts.tasks.import_parsed_songs"
                    ) as import_mock:
                        import_mock.return_value = mock.Mock(
                            songs_created=1, songs_updated=0, warnings=[]
                        )
                        result = process_pdf_chart(self.chart_import.pk)

        self.chart_import.refresh_from_db()
        self.assertEqual(result["status"], ChartImportStatus.COMPLETE)
        self.assertEqual(self.chart_import.status, ChartImportStatus.COMPLETE)
        self.assertEqual(self.chart_import.page_count, 1)
        self.assertEqual(self.chart_import.pages_succeeded, 1)
        self.assertEqual(self.chart_import.pages_failed, 0)
        self.assertIsNotNone(self.chart_import.completed_at)

    def test_songs_backfilled_to_chart_import(self) -> None:
        """Songs in the target Songbook get ``import_run = chart_import``."""
        # Pre-create a Song in the target Songbook (the importer's mock
        # is a no-op for actual creation, so we simulate the outcome).
        s = Song.objects.create(
            slug="happy-omr-song",
            title="Happy",
            songbook=self.songbook,
            import_source=ImportSource.OMR_PDF,
        )
        workspace = self.media_root / "ws-backfill"
        mscz = _make_mscz_file(workspace)
        with mock.patch(
            "apps.charts.tasks.run_one_pdf",
            return_value=OmrOutcome(mscz_path=mscz),
        ), mock.patch(
            "apps.charts.tasks._workspace_dir", return_value=workspace
        ), mock.patch(
            "apps.charts.tasks.parse_path", return_value=[]
        ), mock.patch(
            "apps.charts.tasks.import_parsed_songs",
            return_value=mock.Mock(
                songs_created=0, songs_updated=1, warnings=[]
            ),
        ):
            process_pdf_chart(self.chart_import.pk)

        s.refresh_from_db()
        self.assertEqual(s.import_run, self.chart_import)


@override_settings(MEDIA_ROOT="/tmp/ellington-test-media-81-fail")
class TestProcessPdfChartFailurePaths(TestCase):
    """Each error class lands as FAILED with the right error_log shape."""

    def setUp(self) -> None:
        self.media_root = Path("/tmp/ellington-test-media-81-fail")
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.chart_import = _chart_import(
            file_ref="pdf_upload/sha-fail.pdf"
        )
        _make_pdf_file(self.media_root, self.chart_import.file_ref)

    def _run_with_orchestrator_error(self, exc_class) -> dict:
        with mock.patch(
            "apps.charts.tasks.run_one_pdf",
            side_effect=exc_class("boom"),
        ), mock.patch(
            "apps.charts.tasks._workspace_dir",
            return_value=self.media_root / "ws-fail",
        ):
            return process_pdf_chart(self.chart_import.pk)

    def test_omr_leadsheet_not_installed_is_failed(self) -> None:
        result = self._run_with_orchestrator_error(OmrLeadsheetNotInstalled)
        self.chart_import.refresh_from_db()
        self.assertEqual(result["status"], ChartImportStatus.FAILED)
        self.assertEqual(
            self.chart_import.status, ChartImportStatus.FAILED
        )
        # error_log records the failure under page index "1"
        self.assertIn("1", self.chart_import.error_log["page_failures"])
        self.assertIn(
            "not installed",
            self.chart_import.error_log["page_failures"]["1"],
        )

    def test_pipeline_failure_is_failed(self) -> None:
        result = self._run_with_orchestrator_error(OmrPipelineFailure)
        self.assertEqual(result["status"], ChartImportStatus.FAILED)
        self.chart_import.refresh_from_db()
        self.assertEqual(self.chart_import.pages_failed, 1)
        self.assertEqual(self.chart_import.pages_succeeded, 0)

    def test_missing_pdf_is_failed(self) -> None:
        # Different ChartImport whose file_ref points at a missing path
        ci = _chart_import(file_ref="pdf_upload/missing.pdf")
        result = process_pdf_chart(ci.pk)
        self.assertEqual(result["status"], ChartImportStatus.FAILED)
        ci.refresh_from_db()
        self.assertIn(
            "PDF file missing",
            ci.error_log["page_failures"]["1"],
        )

    def test_task_with_missing_chart_import_returns_not_found(self) -> None:
        result = process_pdf_chart(999999)
        self.assertEqual(result["status"], "not-found")


@override_settings(MEDIA_ROOT="/tmp/ellington-test-media-81-dispatch")
class TestDispatchPdfChart(TestCase):
    """``dispatch_pdf_chart`` helper — race-fix discipline."""

    def setUp(self) -> None:
        self.media_root = Path("/tmp/ellington-test-media-81-dispatch")
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.chart_import = _chart_import(
            file_ref="pdf_upload/sha-disp.pdf"
        )

    def test_sets_queued_status_and_task_id(self) -> None:
        with mock.patch(
            "apps.charts.tasks.process_pdf_chart.delay"
        ) as mock_delay:
            mock_delay.return_value = mock.Mock(id="fake-task-id")
            task_id = dispatch_pdf_chart(self.chart_import)
        self.assertEqual(task_id, "fake-task-id")
        self.chart_import.refresh_from_db()
        self.assertEqual(
            self.chart_import.status, ChartImportStatus.QUEUED
        )
        self.assertEqual(self.chart_import.task_id, "fake-task-id")

    def test_queued_status_set_before_delay_call(self) -> None:
        """Race-fix: status flips to QUEUED *before* .delay() returns.

        Mirror of the practice/tasks.py test from #69 — if the worker
        could pick up the row before status flipped, RUNNING-from-PENDING
        would be a real transition we don't allow.
        """
        observed_status: list[str] = []

        def fake_delay(ci_pk):
            observed_status.append(
                ChartImport.objects.get(pk=ci_pk).status
            )
            return mock.Mock(id="fake-task-id")

        with mock.patch(
            "apps.charts.tasks.process_pdf_chart.delay",
            side_effect=fake_delay,
        ):
            dispatch_pdf_chart(self.chart_import)

        self.assertEqual(observed_status, [ChartImportStatus.QUEUED])

    def test_broker_failure_returns_none_and_reverts_status(self) -> None:
        self.chart_import.status = ChartImportStatus.PENDING
        self.chart_import.save()
        with mock.patch(
            "apps.charts.tasks.process_pdf_chart.delay",
            side_effect=Exception("broker down"),
        ):
            task_id = dispatch_pdf_chart(self.chart_import)
        self.assertIsNone(task_id)
        self.chart_import.refresh_from_db()
        # Stays PENDING — caller can retry without an orphan QUEUED row
        self.assertEqual(
            self.chart_import.status, ChartImportStatus.PENDING
        )


class TestPathTraversalGuard(TestCase):
    """``_resolve_pdf_path`` refuses file_refs escaping MEDIA_ROOT."""

    @override_settings(MEDIA_ROOT="/tmp/ellington-test-media-81-trav")
    def test_traversal_path_raises(self) -> None:
        from apps.charts.tasks import _resolve_pdf_path

        with self.assertRaises(ValueError):
            _resolve_pdf_path("../../etc/passwd")
