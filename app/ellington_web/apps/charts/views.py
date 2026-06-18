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


# ---------------------------------------------------------------------------
# Chart comments (epic #96 sub-ticket e / #114)
# ---------------------------------------------------------------------------


@login_required
@require_POST
def add_chart_comment(request):
    """POST a new chart comment. Exactly one of song_id / section_id /
    chord_event_id must be set; the view rejects all-blank and multiple."""
    from .models import ChartComment, ChordEvent, Section, Song

    song_id = (request.POST.get("song_id") or "").strip()
    section_id = (request.POST.get("section_id") or "").strip()
    chord_event_id = (request.POST.get("chord_event_id") or "").strip()
    body = (request.POST.get("body") or "").strip()

    if not body:
        return _redirect_back_with_message(
            request, "comment can't be empty", "error",
        )

    set_anchors = sum(1 for v in (song_id, section_id, chord_event_id) if v)
    if set_anchors != 1:
        return _redirect_back_with_message(
            request,
            "exactly one of song_id / section_id / chord_event_id required",
            "error",
        )

    song = section = chord_event = None
    if song_id:
        song = get_object_or_404(Song, pk=song_id)
    elif section_id:
        section = get_object_or_404(Section, pk=section_id)
    else:
        chord_event = get_object_or_404(ChordEvent, pk=chord_event_id)

    parent_id_raw = (request.POST.get("parent_id") or "").strip()
    parent = None
    if parent_id_raw:
        parent_qs = ChartComment.objects.filter(pk=parent_id_raw)
        if song:
            parent_qs = parent_qs.filter(song=song)
        elif section:
            parent_qs = parent_qs.filter(section=section)
        else:
            parent_qs = parent_qs.filter(chord_event=chord_event)
        parent = parent_qs.first()

    ChartComment.objects.create(
        song=song, section=section, chord_event=chord_event,
        author=request.user, body=body, parent=parent,
    )
    return _redirect_back_with_message(request, "comment posted", "success")


@login_required
@require_POST
def delete_chart_comment(request, comment_pk):
    """Soft-delete. Author OR Admin OR Pedagogue may delete."""
    from django.utils import timezone

    from apps.core.roles import is_admin, is_pedagogue

    from .models import ChartComment

    comment = get_object_or_404(ChartComment, pk=comment_pk)
    is_author = comment.author_id == request.user.pk
    can_moderate = is_admin(request.user) or is_pedagogue(request.user)
    if not (is_author or can_moderate):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("You can't delete this comment.")

    if comment.deleted_at is None:
        comment.deleted_at = timezone.now()
        comment.save(update_fields=["deleted_at"])
    return _redirect_back_with_message(request, "comment deleted", "info")


@login_required
@require_POST
def edit_chart_comment(request, comment_pk):
    """Edit body. Author-only. Refuses deleted comments (410)."""
    from django.utils import timezone

    from .models import ChartComment

    comment = get_object_or_404(ChartComment, pk=comment_pk)
    if comment.author_id != request.user.pk:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("You can only edit your own comment.")
    if comment.deleted_at is not None:
        from django.http import HttpResponseGone

        return HttpResponseGone("Comment is deleted.")

    body = (request.POST.get("body") or "").strip()
    if not body:
        return _redirect_back_with_message(
            request, "comment can't be empty", "error",
        )

    comment.body = body
    comment.edited_at = timezone.now()
    comment.save(update_fields=["body", "edited_at"])
    return _redirect_back_with_message(request, "comment edited", "success")


def _redirect_back_with_message(request, msg: str, level: str):
    """Helper — redirect to HTTP_REFERER or chart list with a flash msg."""
    if level == "error":
        messages.error(request, msg)
    elif level == "success":
        messages.success(request, msg)
    else:
        messages.info(request, msg)
    referer = request.META.get("HTTP_REFERER")
    if referer:
        return HttpResponseRedirect(referer)
    return redirect("charts:import_list")


# ---------------------------------------------------------------------------
# Songbook sharing (epic #96 sub-ticket c / #137)
# ---------------------------------------------------------------------------


@login_required
def songbook_list(request):
    """Accessible-Songbook list: public + mine + shared-with-me + studio-scoped."""
    from django.db.models import Q

    from apps.practice.models import StudioMember, StudioRole

    from .models import Songbook, SongbookShare, SongbookVisibility

    my_studio_ids = (
        StudioMember.objects
        .filter(user=request.user)
        .exclude(role=StudioRole.BANNED)
        .values_list("studio_id", flat=True)
    )
    shared_ids = (
        SongbookShare.objects
        .filter(recipient=request.user)
        .values_list("songbook_id", flat=True)
    )

    qs = (
        Songbook.objects
        .filter(
            Q(visibility=SongbookVisibility.PUBLIC)
            | Q(owner=request.user)
            | Q(pk__in=shared_ids)
            | Q(
                visibility=SongbookVisibility.STUDIO,
                studio_id__in=my_studio_ids,
            )
        )
        .distinct()
        .order_by("title")
    )

    return render(request, "charts/songbook_list.html", {
        "songbooks": qs,
    })


@login_required
@require_http_methods(["GET", "POST"])
def songbook_share(request, pk: int):
    """Share a Songbook with another user. Owner-only."""
    from django.contrib.auth import get_user_model

    from .models import Songbook, SongbookShare
    from .permissions import is_songbook_owner

    songbook = get_object_or_404(Songbook, pk=pk)
    if not is_songbook_owner(request.user, songbook):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Only the owner may share.")

    User = get_user_model()
    if request.method == "POST":
        recipient_lookup = (request.POST.get("recipient_lookup") or "").strip()
        share_note = (request.POST.get("share_note") or "").strip()

        if not recipient_lookup:
            messages.error(request, "recipient required")
            return redirect("charts:songbook_share", pk=pk)

        recipient = (
            User.objects.filter(email__iexact=recipient_lookup).first()
            or User.objects.filter(username__iexact=recipient_lookup).first()
        )
        if recipient is None:
            messages.error(request, f"no user matches {recipient_lookup!r}")
            return redirect("charts:songbook_share", pk=pk)
        if recipient.pk == request.user.pk:
            messages.error(request, "you can't share with yourself")
            return redirect("charts:songbook_share", pk=pk)

        SongbookShare.objects.get_or_create(
            songbook=songbook, recipient=recipient,
            defaults={"sharer": request.user, "share_note": share_note},
        )
        messages.success(
            request, f"shared with {recipient.username}",
        )
        return redirect("charts:songbook_list")

    return render(request, "charts/songbook_share.html", {
        "songbook": songbook,
    })


@login_required
@require_POST
def songbook_visibility(request, pk: int):
    """Toggle visibility. Owner-only. POST body: visibility=<private|studio|public>,
    studio_slug=<slug> (when visibility=studio)."""
    from .models import Songbook, SongbookVisibility
    from .permissions import is_songbook_owner

    songbook = get_object_or_404(Songbook, pk=pk)
    if not is_songbook_owner(request.user, songbook):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Only the owner may change visibility.")

    visibility = (request.POST.get("visibility") or "").strip()
    valid = {c[0] for c in SongbookVisibility.choices}
    if visibility not in valid:
        messages.error(request, "invalid visibility value")
        return redirect("charts:songbook_list")

    songbook.visibility = visibility
    if visibility == SongbookVisibility.STUDIO:
        from apps.practice.models import Studio

        studio_slug = (request.POST.get("studio_slug") or "").strip()
        if not studio_slug:
            messages.error(request, "studio_slug required for studio scope")
            return redirect("charts:songbook_list")
        studio = Studio.objects.filter(slug=studio_slug).first()
        if studio is None:
            messages.error(request, f"unknown studio {studio_slug!r}")
            return redirect("charts:songbook_list")
        songbook.studio = studio
    else:
        songbook.studio = None
    songbook.save(update_fields=["visibility", "studio"])
    messages.success(request, f"visibility set to {visibility}")
    return redirect("charts:songbook_list")
