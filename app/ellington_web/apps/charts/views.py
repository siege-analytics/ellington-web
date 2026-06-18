"""Views for the charts UI (Phase 4-PDF / #82).

Owner-only enforcement on list and detail — practitioners only see
their own ChartImports. Anonymous → login redirect; authenticated
non-owner accessing someone else's ChartImport → 404 (avoiding
existence-leak via 403).
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import PDFUploadForm
from .models import ChartImport, ChartImportStatus
from .tasks import dispatch_pdf_chart


@login_required
@require_http_methods(["GET", "POST"])
def upload_pdf_chart(request):
    """PDF upload form view at /charts/upload-pdf/."""
    if request.method == "POST":
        form = PDFUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                chart_import, dispatched = form.save(user=request.user)
            except ValueError as exc:
                # store_pdf_upload's magic-byte sniff raises ValueError
                # for non-PDF content. Surface to the form layer.
                form.add_error("pdf", str(exc))
            else:
                if dispatched:
                    messages.success(
                        request,
                        f"PDF queued for processing (import #{chart_import.pk}).",
                    )
                else:
                    messages.info(
                        request,
                        f"This PDF was already uploaded — opening existing import #{chart_import.pk}.",
                    )
                return HttpResponseRedirect(
                    reverse("charts:import_detail", args=[chart_import.pk])
                )
    else:
        form = PDFUploadForm()
    return render(request, "charts/upload.html", {"form": form})


@login_required
def chart_import_list(request):
    """Owner's ChartImport list at /charts/imports/.

    Filter by status via ``?status=<value>``; sticky to last filter via
    session storage so the practitioner doesn't lose context when
    navigating back from a detail page.
    """
    status_filter = request.GET.get("status", "").strip()
    valid_statuses = {choice[0] for choice in ChartImportStatus.choices}

    if status_filter and status_filter not in valid_statuses:
        status_filter = ""

    # Sticky filter behavior
    if status_filter:
        request.session["chart_import_status_filter"] = status_filter
    elif "status" not in request.GET:
        status_filter = request.session.get("chart_import_status_filter", "")

    qs = ChartImport.objects.filter(user=request.user).select_related("source_songbook")
    if status_filter:
        qs = qs.filter(status=status_filter)

    return render(request, "charts/import_list.html", {
        "imports": qs,
        "status_filter": status_filter,
        "statuses": ChartImportStatus.choices,
    })


@login_required
def chart_import_detail(request, pk: int):
    """ChartImport detail at /charts/imports/<pk>/. Owner-only.

    404 (not 403) on non-owner access to avoid leaking existence of
    other users' imports.
    """
    chart_import = get_object_or_404(
        ChartImport.objects.select_related("source_songbook"),
        pk=pk,
        user=request.user,
    )

    page_rows = _build_page_rows(chart_import)

    return render(request, "charts/import_detail.html", {
        "chart_import": chart_import,
        "page_rows": page_rows,
        "songs": chart_import.songs.all() if hasattr(chart_import, "songs") else [],
    })


@login_required
@require_POST
def chart_import_reprocess(request, pk: int):
    """POST-only re-process trigger. Mirrors recording_reanalyze
    pattern from #69."""
    chart_import = get_object_or_404(
        ChartImport, pk=pk, user=request.user,
    )

    page_idx_raw = request.POST.get("page_idx", "").strip()
    if page_idx_raw:
        # Per-page retry — clear that page's failure entry so the
        # orchestrator picks it up on the next pass. The Celery task
        # itself decides whether to support partial re-runs; v1 falls
        # back to a full dispatch and lets the worker skip succeeded
        # pages by SHA.
        try:
            page_idx = int(page_idx_raw)
        except ValueError:
            messages.error(request, "invalid page index")
            return redirect("charts:import_detail", pk=pk)

        failures = (chart_import.error_log or {}).get("page_failures", {})
        failures.pop(str(page_idx), None)
        chart_import.error_log = {
            **(chart_import.error_log or {}),
            "page_failures": failures,
        }
        chart_import.save(update_fields=["error_log"])
        messages.info(request, f"Page {page_idx} marked for re-processing.")
    else:
        messages.info(request, "Re-processing full PDF.")

    dispatch_pdf_chart(chart_import)
    return redirect("charts:import_detail", pk=pk)


def _build_page_rows(chart_import: ChartImport) -> list[dict]:
    """Build the per-page table rows for the detail view.

    Each row: {page_idx (int), status (str), warnings (list[str]),
    failure (str|None), song (Song|None)}. Driven by
    chart_import.page_count + error_log + the reverse Song relation.
    """
    if chart_import.page_count is None:
        return []

    error_log = chart_import.error_log or {}
    page_warnings = error_log.get("page_warnings", {}) or {}
    page_failures = error_log.get("page_failures", {}) or {}

    # Build a quick {page_idx → Song} lookup from chart_import.songs
    # via the page_idx_in_import attribute if it exists on Song.
    # Song model doesn't yet expose page_idx_in_import (lands in a
    # later orchestrator change). Fall back to no per-page Song
    # linkage; the row still renders the warnings + failure cleanly.
    page_to_song: dict[int, object] = {}
    for song in chart_import.songs.all():
        idx = getattr(song, "page_idx_in_import", None)
        if idx is not None:
            page_to_song[int(idx)] = song

    rows = []
    for page_idx in range(chart_import.page_count):
        key = str(page_idx)
        warnings = page_warnings.get(key, [])
        failure = page_failures.get(key)
        song = page_to_song.get(page_idx)
        if failure:
            status = "FAILED"
        elif song is not None:
            status = "OK"
        elif chart_import.status in (
            ChartImportStatus.PENDING, ChartImportStatus.QUEUED,
            ChartImportStatus.RUNNING,
        ):
            status = "PENDING"
        else:
            status = "UNKNOWN"
        rows.append({
            "page_idx": page_idx,
            "status": status,
            "warnings": warnings,
            "failure": failure,
            "song": song,
        })
    return rows
