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

import shutil
import uuid
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
    return get_user_model().objects.create_user(
        f"{label}-{uuid.uuid4().hex[:8]}", password="pw"
    )


def _songbook(slug: str | None = None) -> Songbook:
    return Songbook.objects.create(
        slug=slug or f"sb-{uuid.uuid4().hex[:8]}",
        title="OMR fixture",
    )


def _unique_media_root(label: str) -> str:
    """Per-test MEDIA_ROOT — keeps parallel test runs from cross-contaminating.

    Plugin-agent #85 review MEDIUM: the original shared
    ``/tmp/ellington-test-media-81*`` paths leaked state across
    parallel pytest workers. uuid-suffixed dirs sidestep the issue.
    """
    return f"/tmp/ellington-test-media-{label}-{uuid.uuid4().hex[:8]}"


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


class TestProcessPdfChartHappyPath(TestCase):
    """Successful end-to-end: PDF on disk → mocked omr-leadsheet → Songs imported."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.media_root_str = _unique_media_root("happy")
        cls.media_root = Path(cls.media_root_str)
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root_str)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.songbook = _songbook()
        self.chart_import = _chart_import(
            songbook=self.songbook,
            file_ref="pdf_upload/sha-happy.pdf",
        )
        # Promote to QUEUED so the new precondition guard lets the
        # task run. dispatch_pdf_chart normally does this; tests
        # call the task directly so we set it manually.
        self.chart_import.status = ChartImportStatus.QUEUED
        self.chart_import.save(update_fields=["status"])
        _make_pdf_file(self.media_root, self.chart_import.file_ref)

    def test_running_then_complete(self) -> None:
        workspace = self.media_root / "ws-happy"
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
                songs_created=1,
                songs_updated=0,
                warnings=[],
                touched_song_pks=set(),
            ),
        ):
            result = process_pdf_chart(self.chart_import.pk)

        self.chart_import.refresh_from_db()
        self.assertEqual(result["status"], ChartImportStatus.COMPLETE)
        self.assertEqual(self.chart_import.status, ChartImportStatus.COMPLETE)
        self.assertEqual(self.chart_import.page_count, 1)
        self.assertEqual(self.chart_import.pages_succeeded, 1)
        self.assertEqual(self.chart_import.pages_failed, 0)
        self.assertIsNotNone(self.chart_import.completed_at)

    def test_only_touched_songs_get_import_run_backfilled(self) -> None:
        """Songs the importer touched in this run get ``import_run`` —
        pre-existing Songs in the same songbook MUST NOT.

        Plugin-agent #85 review HIGH: the original implementation
        used ``Song.objects.filter(songbook__slug=...).update(...)``
        which painted EVERY song in the songbook with the new
        import_run FK. Fixed by reading ``ImportSummary.touched_song_pks``
        and updating only those PKs.
        """
        # Pre-existing Song in the same songbook — MUST NOT get
        # import_run set by this run.
        bystander = Song.objects.create(
            slug="bystander-song",
            title="Pre-existing",
            songbook=self.songbook,
            import_source=ImportSource.HAND_ENTERED,
        )
        # Song the importer "touched" in this run
        touched = Song.objects.create(
            slug="omr-touched-song",
            title="Touched",
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
                songs_created=0,
                songs_updated=1,
                warnings=[],
                touched_song_pks={touched.pk},
            ),
        ):
            process_pdf_chart(self.chart_import.pk)

        touched.refresh_from_db()
        bystander.refresh_from_db()
        self.assertEqual(touched.import_run, self.chart_import)
        # The bystander must NOT have been painted — this is the bug fix
        self.assertIsNone(bystander.import_run)
        self.assertEqual(bystander.import_source, ImportSource.HAND_ENTERED)


class TestProcessPdfChartFailurePaths(TestCase):
    """Each error class lands as FAILED with the right error_log shape."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.media_root_str = _unique_media_root("fail")
        cls.media_root = Path(cls.media_root_str)
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root_str)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.chart_import = _chart_import(
            file_ref="pdf_upload/sha-fail.pdf"
        )
        self.chart_import.status = ChartImportStatus.QUEUED
        self.chart_import.save(update_fields=["status"])
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
        ci.status = ChartImportStatus.QUEUED
        ci.save(update_fields=["status"])
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

    def test_retry_clears_stale_error_log_and_force_runs_omr(self) -> None:
        """Retry path: stale error_log is cleared and run_one_pdf gets force=True.

        Plugin-agent #85 review CRITICAL (force=True on retry) and
        MEDIUM (stale error_log lingers across re-dispatch).
        """
        # Stage a prior failure on the row — a real retry would
        # find error_log populated and status FAILED.
        self.chart_import.error_log = {
            "page_warnings": {},
            "page_failures": {"1": "old failure message"},
        }
        self.chart_import.pages_failed = 1
        self.chart_import.status = ChartImportStatus.QUEUED
        self.chart_import.save()

        workspace = self.media_root / "ws-retry"
        mscz = _make_mscz_file(workspace)

        observed_force: list[bool] = []

        def fake_run_one_pdf(pdf_path, ws_dir, *, force=False, with_oemer=False):
            observed_force.append(force)
            return OmrOutcome(mscz_path=mscz)

        with mock.patch(
            "apps.charts.tasks.run_one_pdf", side_effect=fake_run_one_pdf
        ), mock.patch(
            "apps.charts.tasks._workspace_dir", return_value=workspace
        ), mock.patch(
            "apps.charts.tasks.parse_path", return_value=[]
        ), mock.patch(
            "apps.charts.tasks.import_parsed_songs",
            return_value=mock.Mock(
                songs_created=1, songs_updated=0, warnings=[],
                touched_song_pks=set(),
            ),
        ):
            # Simulate Celery's retries counter at 2 (third attempt)
            fake_request = mock.Mock(retries=2)
            with mock.patch.object(
                process_pdf_chart, "request", fake_request, create=True
            ):
                process_pdf_chart(self.chart_import.pk)

        # force=True must have been passed because retries > 0
        self.assertEqual(observed_force, [True])
        # Stale error_log got cleared by the RUNNING precondition update
        self.chart_import.refresh_from_db()
        self.assertEqual(
            self.chart_import.error_log.get("page_failures", {}),
            {},
        )
        self.assertEqual(self.chart_import.status, ChartImportStatus.COMPLETE)


class TestRunningPrecondition(TestCase):
    """The RUNNING-flip precondition guards against concurrent dispatch.

    Plugin-agent #85 review MEDIUM: two workers picking up a
    redelivered message can't both proceed. The .update() with
    status__in=(QUEUED, PENDING, RUNNING) returns 0 rows for the
    loser, who bails with a 'skipped' result.
    """

    def test_complete_chart_import_is_skipped(self) -> None:
        ci = _chart_import(file_ref=f"pdf_upload/{uuid.uuid4().hex}.pdf")
        ci.status = ChartImportStatus.COMPLETE
        ci.save(update_fields=["status"])
        result = process_pdf_chart(ci.pk)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["current_status"], ChartImportStatus.COMPLETE)

    def test_canceled_chart_import_is_skipped(self) -> None:
        ci = _chart_import(file_ref=f"pdf_upload/{uuid.uuid4().hex}.pdf")
        ci.status = ChartImportStatus.CANCELED
        ci.save(update_fields=["status"])
        result = process_pdf_chart(ci.pk)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["current_status"], ChartImportStatus.CANCELED)


class TestDispatchPdfChart(TestCase):
    """``dispatch_pdf_chart`` helper — race-fix discipline."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.media_root_str = _unique_media_root("dispatch")
        cls.media_root = Path(cls.media_root_str)
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root_str)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
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

    def test_traversal_path_raises(self) -> None:
        from apps.charts.tasks import _resolve_pdf_path

        with override_settings(MEDIA_ROOT=_unique_media_root("trav")):
            with self.assertRaises(ValueError):
                _resolve_pdf_path("../../etc/passwd")


class TestCleanupBehavior(TestCase):
    """Workspace cleanup honors the keep-on-complete settings flag.

    Plugin-agent #85 review MEDIUM. FAILED runs preserve workspace
    for post-mortem (covered by the failure-path tests above which
    don't assert cleanup). COMPLETE runs respect the flag.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.media_root_str = _unique_media_root("cleanup")
        cls.media_root = Path(cls.media_root_str)
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root_str)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.chart_import = _chart_import(
            file_ref="pdf_upload/sha-clean.pdf"
        )
        self.chart_import.status = ChartImportStatus.QUEUED
        self.chart_import.save(update_fields=["status"])
        _make_pdf_file(self.media_root, self.chart_import.file_ref)

    def _run_to_complete(self) -> Path:
        """Helper: run process_pdf_chart through COMPLETE, return workspace path."""
        workspace = self.media_root / "ws-clean"
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
                songs_created=1, songs_updated=0, warnings=[],
                touched_song_pks=set(),
            ),
        ):
            process_pdf_chart(self.chart_import.pk)
        return workspace

    def test_workspace_removed_after_complete_by_default(self) -> None:
        workspace = self._run_to_complete()
        self.assertFalse(workspace.exists())

    @override_settings(ELLINGTON_OMR_KEEP_WORKSPACE_ON_COMPLETE=True)
    def test_workspace_preserved_when_flag_set(self) -> None:
        workspace = self._run_to_complete()
        self.assertTrue(workspace.exists())
