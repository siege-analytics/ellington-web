"""Tests for the charts UI (Phase 4-PDF / #82).

Covers:
- login-required on all three views (redirect to login for anonymous)
- owner-only isolation on list + detail (no leakage between users)
- POST upload → ChartImport row created + dispatched (mocked)
- Idempotent re-upload: same SHA returns existing ChartImport
- Magic-byte sniff rejects non-PDF content with .pdf extension
- PARTIAL list view rendering doesn't crash
- Per-page row computation for multi-page detail view
- Reprocess: full + per-page paths, POST-only, owner-only
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.charts.models import ChartImport, ChartImportStatus, Songbook
from apps.charts.views import _build_page_rows


User = get_user_model()


def _pdf_upload(name: str = "test.pdf", extra: bytes = b"") -> SimpleUploadedFile:
    """Build a SimpleUploadedFile with valid PDF magic bytes."""
    body = b"%PDF-1.4\n" + extra + b"\n%%EOF\n"
    return SimpleUploadedFile(name=name, content=body, content_type="application/pdf")


class _BaseChartsViewTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.tmpdir)
        self.override.enable()
        self.alice = User.objects.create_user(username="alice")
        self.bob = User.objects.create_user(username="bob")

    def tearDown(self):
        self.override.disable()


class LoginRequiredTests(_BaseChartsViewTests):
    def test_upload_view_redirects_anonymous(self):
        response = self.client.get(reverse("charts:upload_pdf"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_list_view_redirects_anonymous(self):
        response = self.client.get(reverse("charts:import_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_detail_view_redirects_anonymous(self):
        ci = ChartImport.objects.create(
            user=self.alice, file_ref="pdf_upload/abc.pdf",
        )
        response = self.client.get(reverse("charts:import_detail", args=[ci.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


class OwnerIsolationTests(_BaseChartsViewTests):
    def test_list_only_shows_own_imports(self):
        sb_alice = Songbook.objects.create(title="Alice's book")
        sb_bob = Songbook.objects.create(title="Bob's book")
        ChartImport.objects.create(
            user=self.alice, file_ref="pdf_upload/a.pdf", source_songbook=sb_alice,
        )
        ChartImport.objects.create(
            user=self.bob, file_ref="pdf_upload/b.pdf", source_songbook=sb_bob,
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("charts:import_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice's book")
        self.assertNotContains(response, "Bob's book")

    def test_detail_404s_for_other_users_import(self):
        ci = ChartImport.objects.create(
            user=self.alice, file_ref="pdf_upload/alice.pdf",
        )
        self.client.force_login(self.bob)
        response = self.client.get(reverse("charts:import_detail", args=[ci.pk]))
        self.assertEqual(response.status_code, 404)


class UploadFlowTests(_BaseChartsViewTests):
    @patch("apps.charts.forms.dispatch_pdf_chart")
    def test_post_upload_creates_chart_import_and_dispatches(self, mock_dispatch):
        self.client.force_login(self.alice)
        sb = Songbook.objects.create(title="My book")
        response = self.client.post(
            reverse("charts:upload_pdf"),
            {"pdf": _pdf_upload(extra=b"a"), "songbook": sb.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChartImport.objects.filter(user=self.alice).count(), 1)
        mock_dispatch.assert_called_once()

    @patch("apps.charts.forms.dispatch_pdf_chart")
    def test_idempotent_reupload_same_sha_does_not_redispatch(self, mock_dispatch):
        self.client.force_login(self.alice)
        sb = Songbook.objects.create(title="My book")
        for _ in range(2):
            response = self.client.post(
                reverse("charts:upload_pdf"),
                {"pdf": _pdf_upload(extra=b"identical"), "songbook": sb.pk},
            )
            self.assertEqual(response.status_code, 302)
        self.assertEqual(ChartImport.objects.filter(user=self.alice).count(), 1)
        self.assertEqual(mock_dispatch.call_count, 1)

    def test_magic_byte_sniff_rejects_non_pdf_content(self):
        self.client.force_login(self.alice)
        sb = Songbook.objects.create(title="My book")
        fake = SimpleUploadedFile(
            name="fake.pdf", content=b"not a pdf content",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse("charts:upload_pdf"),
            {"pdf": fake, "songbook": sb.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChartImport.objects.count(), 0)
        self.assertContains(response, "%PDF magic bytes")

    @patch("apps.charts.forms.dispatch_pdf_chart")
    def test_post_upload_creates_new_songbook_when_name_given(self, mock_dispatch):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:upload_pdf"),
            {"pdf": _pdf_upload(extra=b"x"), "new_songbook_name": "Fresh book"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Songbook.objects.filter(title="Fresh book").exists())
        ci = ChartImport.objects.get(user=self.alice)
        self.assertEqual(ci.source_songbook.title, "Fresh book")

    def test_rejects_both_blank_songbook(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:upload_pdf"),
            {"pdf": _pdf_upload(extra=b"y")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pick an existing songbook")
        self.assertEqual(ChartImport.objects.count(), 0)

    def test_rejects_both_songbook_and_new_name(self):
        self.client.force_login(self.alice)
        sb = Songbook.objects.create(title="Existing")
        response = self.client.post(
            reverse("charts:upload_pdf"),
            {
                "pdf": _pdf_upload(extra=b"z"),
                "songbook": sb.pk,
                "new_songbook_name": "Also new",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not both")


class PartialAndPageRowTests(_BaseChartsViewTests):
    def test_list_view_renders_partial_status_without_crash(self):
        ChartImport.objects.create(
            user=self.alice,
            file_ref="pdf_upload/x.pdf",
            status=ChartImportStatus.PARTIAL,
            page_count=10,
            pages_succeeded=7,
            pages_failed=3,
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("charts:import_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "10 pages")
        self.assertContains(response, "7 succeeded")
        self.assertContains(response, "3 failed")

    def test_build_page_rows_emits_failed_then_pending(self):
        ci = ChartImport(
            page_count=3,
            error_log={"page_failures": {"1": "OMR crash"}},
            status=ChartImportStatus.RUNNING,
        )
        rows = _build_page_rows(ci)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["status"], "PENDING")
        self.assertEqual(rows[1]["status"], "FAILED")
        self.assertEqual(rows[1]["failure"], "OMR crash")

    def test_build_page_rows_empty_when_page_count_none(self):
        ci = ChartImport(page_count=None)
        self.assertEqual(_build_page_rows(ci), [])


class ReprocessTests(_BaseChartsViewTests):
    @patch("apps.charts.views.dispatch_pdf_chart")
    def test_reprocess_full_dispatches(self, mock_dispatch):
        ci = ChartImport.objects.create(
            user=self.alice, file_ref="pdf_upload/x.pdf",
        )
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:import_reprocess", args=[ci.pk])
        )
        self.assertEqual(response.status_code, 302)
        mock_dispatch.assert_called_once()

    @patch("apps.charts.views.dispatch_pdf_chart")
    def test_reprocess_per_page_clears_failure_entry(self, mock_dispatch):
        ci = ChartImport.objects.create(
            user=self.alice,
            file_ref="pdf_upload/x.pdf",
            error_log={"page_failures": {"2": "OMR crash"}},
        )
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:import_reprocess", args=[ci.pk]),
            {"page_idx": "2"},
        )
        self.assertEqual(response.status_code, 302)
        ci.refresh_from_db()
        self.assertNotIn("2", ci.error_log.get("page_failures", {}))
        mock_dispatch.assert_called_once()

    def test_reprocess_only_accepts_post(self):
        ci = ChartImport.objects.create(
            user=self.alice, file_ref="pdf_upload/x.pdf",
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("charts:import_reprocess", args=[ci.pk]))
        self.assertEqual(response.status_code, 405)

    def test_reprocess_404s_for_other_users_import(self):
        ci = ChartImport.objects.create(
            user=self.alice, file_ref="pdf_upload/x.pdf",
        )
        self.client.force_login(self.bob)
        response = self.client.post(reverse("charts:import_reprocess", args=[ci.pk]))
        self.assertEqual(response.status_code, 404)
