"""Practice-flow views — list, create, detail, delete PracticeSessions.

All views are ``@login_required`` (no anonymous access). Permission
isolation is via queryset filtering: a user only ever sees their own
``PracticeSession`` rows.

The detail view walks the linked Song's chord progression so the user
sees what the chart says alongside their recording. Walking is done
inline here (a small Section → Measure → ChordEvent loop) rather than
calling ``apps.charts.timeline.flatten_chord_events`` so this PR
doesn't depend on #64 / PR #64 landing first. After #64 merges, the
inline loop here is a candidate to swap to the helper for consistency.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.charts.models import ChordEvent, Measure, Section

from .forms import PracticeSessionForm
from .models import PracticeSession, Recording
from .tasks import dispatch_analysis


@login_required
def session_list(request: HttpRequest) -> HttpResponse:
    """List the logged-in user's PracticeSessions, newest first."""
    sessions = (
        PracticeSession.objects.filter(user=request.user)
        .select_related("song", "target_preset")
        .prefetch_related("recordings")
    )
    return render(
        request,
        "practice/session_list.html",
        {"sessions": sessions},
    )


@login_required
@require_http_methods(["GET", "POST"])
def session_new(request: HttpRequest) -> HttpResponse:
    """Create-form view for a new practice session + first recording."""
    # ``?song=<id>`` pre-selects a song (used when arriving from a
    # song-detail page in the future).
    initial_song_id = request.GET.get("song")
    try:
        initial_song_id_int = int(initial_song_id) if initial_song_id else None
    except (TypeError, ValueError):
        initial_song_id_int = None

    if request.method == "POST":
        form = PracticeSessionForm(
            request.POST,
            request.FILES,
            initial_song_id=initial_song_id_int,
        )
        if form.is_valid():
            session = form.save(user=request.user)
            # Auto-fire audio analysis on the just-created Recording.
            # If broker is down, dispatch_analysis returns None and the
            # user can manually re-fire from session_detail.
            first_recording = session.recordings.first()
            if first_recording is not None:
                task_id = dispatch_analysis(first_recording)
                if task_id:
                    messages.success(
                        request,
                        f"created session {session.id} — recording uploaded; "
                        f"analysis queued (task {task_id[:12]}...)",
                    )
                else:
                    messages.warning(
                        request,
                        f"created session {session.id} — recording uploaded; "
                        "analysis queue unavailable, use Re-analyze to retry",
                    )
            else:
                messages.success(
                    request,
                    f"created session {session.id} — recording uploaded",
                )
            return redirect("practice:session_detail", pk=session.id)
    else:
        form = PracticeSessionForm(initial_song_id=initial_song_id_int)

    return render(
        request,
        "practice/session_form.html",
        {"form": form},
    )


@login_required
def session_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail view: session metadata + chord progression + audio player."""
    session = get_object_or_404(
        PracticeSession.objects.select_related(
            "song", "target_preset", "backing_track"
        ).prefetch_related("recordings"),
        pk=pk,
        user=request.user,
    )
    recordings = list(session.recordings.all())

    # Walk the song's chord progression in play order. Prefetch the
    # whole tree with the sort orders applied at the queryset level so
    # the inner loops don't refetch — using ``.order_by()`` on a
    # related-manager iterator invalidates ``prefetch_related`` and
    # re-issues SELECTs per section + per measure (~37 queries for a
    # 32-bar 4-section song). Inline here so this PR doesn't depend on
    # apps.charts.timeline (Phase 1b / PR #64); after #64 merges we can
    # swap to ``flatten_chord_events``.
    chord_rows: list[dict] = []
    if session.song is not None:
        prefetched_sections = (
            session.song.sections.order_by("order_index").prefetch_related(
                Prefetch(
                    "measures",
                    queryset=Measure.objects.order_by(
                        "number_in_section"
                    ).prefetch_related(
                        Prefetch(
                            "chord_events",
                            queryset=ChordEvent.objects.order_by("beat"),
                        )
                    ),
                )
            )
        )
        flat_measure_index = 0
        for section in prefetched_sections:
            for measure in section.measures.all():
                flat_measure_index += 1
                events = list(measure.chord_events.all())
                chord_rows.append(
                    {
                        "flat_measure_index": flat_measure_index,
                        "section_label": section.label,
                        "number_in_section": measure.number_in_section,
                        "chord_events": [
                            (float(e.beat), e.chord_symbol) for e in events
                        ],
                    }
                )

    return render(
        request,
        "practice/session_detail.html",
        {
            "session": session,
            "recordings": recordings,
            "chord_rows": chord_rows,
        },
    )


@login_required
@require_POST
def recording_reanalyze(request: HttpRequest, recording_pk: int) -> HttpResponseRedirect:
    """Manually re-fire analyze_recording on an existing Recording.

    Used when:
      - Auto-fire failed at create time (broker was down)
      - User wants to re-run analysis after the algorithm changes
        (e.g. Phase 3b's real detector lands)
    """
    recording = get_object_or_404(
        Recording.objects.select_related("session"),
        pk=recording_pk,
        session__user=request.user,
    )
    task_id = dispatch_analysis(recording)
    if task_id:
        messages.success(
            request,
            f"re-analysis queued for recording {recording_pk} (task {task_id[:12]}...)",
        )
    else:
        messages.error(
            request,
            f"could not queue re-analysis — broker unreachable",
        )
    return redirect("practice:session_detail", pk=recording.session_id)


@login_required
@require_POST
def session_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    """Destructive: delete a session. CASCADE removes recordings + segments.

    The on-disk Recording files are NOT deleted by CASCADE — Django ORM
    doesn't know about the storage layer. For v0 that's acceptable
    (storage is content-addressed, so leaving an orphaned blob doesn't
    leak user data per-se), but a follow-up ticket should add a
    post_delete signal that removes the file from MEDIA_ROOT.
    """
    session = get_object_or_404(
        PracticeSession,
        pk=pk,
        user=request.user,
    )
    session.delete()
    messages.success(request, f"deleted session {pk}")
    return redirect(reverse("practice:session_list"))


__all__ = [
    "recording_reanalyze",
    "session_delete",
    "session_detail",
    "session_list",
    "session_new",
]


# ---------------------------------------------------------------------------
# Recording sharing + shared-with-me (epic #96 sub-ticket b / #108)
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def share_recording(request: HttpRequest, recording_pk: int) -> HttpResponse:
    """Share a Recording with another user (existing or invited)."""
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    from .forms import ShareRecordingForm

    recording = get_object_or_404(
        Recording.objects.select_related("session"),
        pk=recording_pk,
        session__user=request.user,
    )

    if request.method == "POST":
        form = ShareRecordingForm(
            request.POST, sharer=request.user, recording=recording,
        )
        if form.is_valid():
            share, invite = form.save()
            context = {
                "share": share,
                "invite": invite,
                "sharer": request.user,
                "recording": recording,
                "site_origin": request.build_absolute_uri("/").rstrip("/"),
            }
            if invite is not None:
                context["accept_url"] = request.build_absolute_uri(
                    reverse("core:accept_invite", args=[invite.token])
                )
                subject = "You've been invited to Ellington"
                body_txt = render_to_string("email/invite_to_ellington.txt", context)
                body_html = render_to_string("email/invite_to_ellington.html", context)
                msg = EmailMultiAlternatives(
                    subject=subject, body=body_txt, to=[invite.email],
                )
                msg.attach_alternative(body_html, "text/html")
                msg.send(fail_silently=False)
                messages.success(
                    request,
                    f"Invite sent to {invite.email}. They'll see your recording"
                    " once they sign up.",
                )
            else:
                subject = f"{request.user.username} shared a recording with you"
                body_txt = render_to_string("email/recording_shared.txt", context)
                body_html = render_to_string("email/recording_shared.html", context)
                if share.recipient.email:
                    msg = EmailMultiAlternatives(
                        subject=subject, body=body_txt,
                        to=[share.recipient.email],
                    )
                    msg.attach_alternative(body_html, "text/html")
                    msg.send(fail_silently=False)
                messages.success(
                    request,
                    f"Recording shared with {share.recipient.username}.",
                )
            return redirect("practice:session_detail", pk=recording.session_id)
    else:
        form = ShareRecordingForm(sharer=request.user, recording=recording)

    return render(request, "practice/share_recording.html", {
        "form": form, "recording": recording,
    })


@login_required
def shared_with_me(request: HttpRequest) -> HttpResponse:
    """List Recordings shared *with* the signed-in user."""
    from .models import RecordingShare

    shares = (
        RecordingShare.objects
        .filter(recipient=request.user)
        .select_related("recording__session", "sharer")
        .order_by("-shared_at")
    )
    return render(request, "practice/shared_with_me.html", {"shares": shares})


# ---------------------------------------------------------------------------
# Recording comments (epic #96 sub-ticket d / #110)
# ---------------------------------------------------------------------------


@login_required
@require_POST
def add_recording_comment(request: HttpRequest, recording_pk: int) -> HttpResponse:
    """POST a new comment on a Recording. Comment author = request.user."""
    from .models import Recording, RecordingComment
    from .permissions import can_access_recording

    recording = get_object_or_404(
        Recording.objects.select_related("session"), pk=recording_pk,
    )
    if not can_access_recording(request.user, recording):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("You can't comment on this recording.")

    body = (request.POST.get("body") or "").strip()
    if not body:
        messages.error(request, "comment can't be empty")
        return redirect("practice:session_detail", pk=recording.session_id)

    anchor_ms_raw = (request.POST.get("anchor_ms") or "").strip()
    anchor_ms: int | None = None
    if anchor_ms_raw:
        try:
            anchor_ms = int(anchor_ms_raw)
            if anchor_ms < 0:
                raise ValueError
            if recording.duration_ms and anchor_ms > recording.duration_ms:
                messages.error(
                    request,
                    f"anchor_ms ({anchor_ms}) exceeds recording duration"
                    f" ({recording.duration_ms})",
                )
                return redirect("practice:session_detail", pk=recording.session_id)
        except ValueError:
            messages.error(request, "anchor_ms must be a non-negative integer")
            return redirect("practice:session_detail", pk=recording.session_id)

    parent_id_raw = (request.POST.get("parent_id") or "").strip()
    parent = None
    if parent_id_raw:
        parent = RecordingComment.objects.filter(
            pk=parent_id_raw, recording=recording,
        ).first()

    RecordingComment.objects.create(
        recording=recording,
        author=request.user,
        body=body,
        anchor_ms=anchor_ms,
        parent=parent,
    )
    return redirect("practice:session_detail", pk=recording.session_id)


@login_required
@require_POST
def delete_recording_comment(
    request: HttpRequest, comment_pk: int,
) -> HttpResponse:
    """Soft-delete a comment.

    Allowed if request.user is the comment's author OR the owner of
    the Recording (moderation).
    """
    from django.utils import timezone

    from .models import RecordingComment
    from .permissions import is_recording_owner

    comment = get_object_or_404(
        RecordingComment.objects.select_related("recording__session"),
        pk=comment_pk,
    )
    is_author = comment.author_id == request.user.pk
    is_owner = is_recording_owner(request.user, comment.recording)
    if not (is_author or is_owner):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden(
            "You can't delete this comment."
        )

    if comment.deleted_at is None:
        comment.deleted_at = timezone.now()
        comment.save(update_fields=["deleted_at"])

    return redirect(
        "practice:session_detail", pk=comment.recording.session_id,
    )


@login_required
@require_POST
def edit_recording_comment(
    request: HttpRequest, comment_pk: int,
) -> HttpResponse:
    """Edit a comment's body. Only the comment's author may edit."""
    from django.utils import timezone

    from .models import RecordingComment

    comment = get_object_or_404(
        RecordingComment.objects.select_related("recording__session"),
        pk=comment_pk,
    )
    if comment.author_id != request.user.pk:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("You can only edit your own comment.")
    if comment.deleted_at is not None:
        from django.http import HttpResponseGone

        return HttpResponseGone("Comment is deleted.")

    body = (request.POST.get("body") or "").strip()
    if not body:
        messages.error(request, "comment can't be empty")
        return redirect(
            "practice:session_detail", pk=comment.recording.session_id,
        )

    comment.body = body
    comment.edited_at = timezone.now()
    comment.save(update_fields=["body", "edited_at"])
    return redirect(
        "practice:session_detail", pk=comment.recording.session_id,
    )
