"""Views for the rule-review focus-group surface (epic #96 / #98).

Permission shape:
- Read (rule_list, rule_detail): login-required. We let any signed-in
  user browse — pedagogues self-select what to engage with.
- Write (verdict on rule_detail, add_rule_comment, edit_*, delete own):
  requires apps.core.roles.is_pedagogue. Stranger gets a flash error.
- Admin queue + moderation delete: requires is_staff.
"""

from __future__ import annotations

from collections import OrderedDict
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Q
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseGone,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.roles import is_admin, is_pedagogue
from apps.engine_rules.models import EngineRule
from apps.voicings.fretboard import render_svg
from apps.voicings.lookup import resolve_voicings_for_rule

from .models import (
    PedagogueConfirmation,
    RejectionAxis,
    Response,
    RuleComment,
    Verdict,
)


# ---------------------------------------------------------------------------
# Rule browse + detail
# ---------------------------------------------------------------------------


@login_required
def rule_list(request: HttpRequest) -> HttpResponse:
    """Paginated rule list with per-rule verdict counts + my-verdict."""
    qs = (
        EngineRule.objects.filter(is_active=True)
        .select_related("master", "bundle")
        .annotate(
            accept_count=Count(
                "responses", filter=Q(responses__verdict=Verdict.ACCEPT),
            ),
            close_but_count=Count(
                "responses", filter=Q(responses__verdict=Verdict.CLOSE_BUT),
            ),
            reject_count=Count(
                "responses", filter=Q(responses__verdict=Verdict.REJECT),
            ),
            comment_count=Count(
                "comments",
                filter=Q(comments__deleted_at__isnull=True),
                distinct=True,
            ),
        )
    )

    # Filter knobs
    master_slug = request.GET.get("master", "").strip()
    if master_slug:
        qs = qs.filter(master__slug=master_slug)

    quality = request.GET.get("quality", "").strip()
    if quality:
        qs = qs.filter(quality_binding__contains=[quality])

    my_verdict = request.GET.get("my_verdict", "").strip()
    if my_verdict:
        if my_verdict == "unjudged":
            qs = qs.exclude(responses__user=request.user)
        elif my_verdict in {choice[0] for choice in Verdict.choices}:
            qs = qs.filter(
                responses__user=request.user,
                responses__verdict=my_verdict,
            ).distinct()

    paginator = Paginator(qs.order_by("master__slug", "work_id", "rule_id"), 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Fetch the user's existing verdicts on the current page and pin
    # each onto its rule for template-friendly access (Django templates
    # can't dict-key trivially).
    if is_pedagogue(request.user) or is_admin(request.user):
        rule_pks = [r.pk for r in page_obj.object_list]
        my_responses = {
            r.rule_id: r
            for r in Response.objects.filter(
                rule_id__in=rule_pks, user=request.user,
            )
        }
        for rule in page_obj.object_list:
            response = my_responses.get(rule.pk)
            rule.my_verdict = response.verdict if response else ""
    else:
        for rule in page_obj.object_list:
            rule.my_verdict = ""

    return render(request, "rule_review/rule_list.html", {
        "page_obj": page_obj,
        "verdict_choices": Verdict.choices,
        "filter_master": master_slug,
        "filter_quality": quality,
        "filter_my_verdict": my_verdict,
    })


@login_required
@require_http_methods(["GET", "POST"])
def rule_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Rule detail with verdict form + comment thread."""
    rule = get_object_or_404(
        EngineRule.objects.select_related("master", "bundle"),
        pk=pk,
        is_active=True,
    )

    my_response = Response.objects.filter(rule=rule, user=request.user).first()
    my_confirmation = PedagogueConfirmation.objects.filter(
        rule=rule, user=request.user,
    ).first()

    if request.method == "POST":
        if not is_pedagogue(request.user) and not is_admin(request.user):
            messages.error(
                request,
                "Only pedagogues may submit verdicts. Ask an admin for the role.",
            )
            return redirect("rule_review:rule_detail", pk=pk)

        verdict = (request.POST.get("verdict") or "").strip()
        rejection_axis = (request.POST.get("rejection_axis") or "").strip()
        comment = (request.POST.get("comment") or "").strip()

        if verdict not in {c[0] for c in Verdict.choices}:
            messages.error(request, "Pick a verdict.")
            return redirect("rule_review:rule_detail", pk=pk)

        if verdict != Verdict.ACCEPT:
            if rejection_axis not in {c[0] for c in RejectionAxis.choices}:
                messages.error(
                    request,
                    "Reject / close-but requires a rejection axis.",
                )
                return redirect("rule_review:rule_detail", pk=pk)
            if not comment:
                messages.error(
                    request,
                    "Reject / close-but requires a comment explaining why.",
                )
                return redirect("rule_review:rule_detail", pk=pk)
        else:
            rejection_axis = ""  # accept always clears axis

        Response.objects.update_or_create(
            rule=rule, user=request.user,
            defaults={
                "verdict": verdict,
                "rejection_axis": rejection_axis,
                "comment": comment,
            },
        )
        messages.success(request, "Verdict saved.")
        return redirect("rule_review:rule_detail", pk=pk)

    comments = list(
        rule.comments.select_related("author", "parent").order_by("created_at")
    )

    response_counts = rule.responses.values("verdict").annotate(n=Count("id"))
    counts_map = {row["verdict"]: row["n"] for row in response_counts}

    # Voicing preview candidates + inline SVGs (#286). Zip'd list so
    # the template can iterate one collection instead of parallel
    # indexing. Cap at 6 so a rule with an over-broad quality binding
    # doesn't render 30 diagrams.
    candidate_voicings = list(resolve_voicings_for_rule(rule)[:6])
    voicing_previews = [
        {
            "voicing": v,
            "svg": render_svg(
                strings=v.strings,
                fret_number=v.fret_number,
                visible_frets=v.visible_frets,
                dots=v.dots or [],
                mutes=v.mutes or [],
                open_strings=v.open_strings or [],
            ),
        }
        for v in candidate_voicings
    ]

    return render(request, "rule_review/rule_detail.html", {
        "rule": rule,
        "my_response": my_response,
        "my_confirmation": my_confirmation,
        "verdict_choices": Verdict.choices,
        "axis_choices": RejectionAxis.choices,
        "comments": comments,
        "counts": counts_map,
        "can_write": is_pedagogue(request.user) or is_admin(request.user),
        "confidence_choices": [1, 2, 3, 4, 5],
        "voicing_previews": voicing_previews,
    })


# ---------------------------------------------------------------------------
# Per-axis confirmation (#186 Phase 1)
# ---------------------------------------------------------------------------


@login_required
@require_POST
def confirm_rule(request: HttpRequest, pk: int) -> HttpResponse:
    """Persist a pedagogue's per-axis confirmation for one rule.

    Parallel to the verdict POST on rule_detail: distinct signal,
    distinct form, same edit semantics (update_or_create). Per
    ticket #186 Phase 1.
    """
    rule = get_object_or_404(EngineRule, pk=pk, is_active=True)
    if not is_pedagogue(request.user) and not is_admin(request.user):
        messages.error(
            request,
            "Only pedagogues may submit confirmations. Ask an admin for the role.",
        )
        return redirect("rule_review:rule_detail", pk=pk)

    def _bool(name: str) -> bool:
        return (request.POST.get(name) or "").strip().lower() in {
            "1", "on", "true", "yes",
        }

    confidence_raw = (request.POST.get("overall_confidence") or "").strip()
    confidence = None
    if confidence_raw:
        try:
            confidence = int(confidence_raw)
        except ValueError:
            messages.error(request, "Confidence must be a number 1-5.")
            return redirect("rule_review:rule_detail", pk=pk)
        if not (1 <= confidence <= 5):
            messages.error(request, "Confidence must be in the 1-5 range.")
            return redirect("rule_review:rule_detail", pk=pk)

    # Optional voicing pin (#286). Whitelist against the resolver's
    # candidate set so we can't be told to pin an arbitrary voicing —
    # only ones that actually match this rule.
    voicing_pk_raw = (request.POST.get("voicing_id") or "").strip()
    pinned_voicing = None
    if voicing_pk_raw:
        try:
            voicing_pk = int(voicing_pk_raw)
        except ValueError:
            messages.error(request, "Invalid voicing selection.")
            return redirect("rule_review:rule_detail", pk=pk)
        allowed_ids = set(
            resolve_voicings_for_rule(rule).values_list("pk", flat=True)
        )
        if voicing_pk not in allowed_ids:
            messages.error(
                request,
                "Selected voicing is not a candidate for this rule.",
            )
            return redirect("rule_review:rule_detail", pk=pk)
        from apps.voicings.models import Voicing
        pinned_voicing = Voicing.objects.get(pk=voicing_pk)

    PedagogueConfirmation.objects.update_or_create(
        rule=rule, user=request.user,
        defaults={
            "voicing_confirmed": _bool("voicing_confirmed"),
            "voicing_note": (request.POST.get("voicing_note") or "").strip(),
            "voicing": pinned_voicing,
            "naming_confirmed": _bool("naming_confirmed"),
            "naming_note": (request.POST.get("naming_note") or "").strip(),
            "lesson_confirmed": _bool("lesson_confirmed"),
            "lesson_note": (request.POST.get("lesson_note") or "").strip(),
            "overall_confidence": confidence,
        },
    )
    messages.success(request, "Confirmation saved.")
    return redirect("rule_review:rule_detail", pk=pk)


# ---------------------------------------------------------------------------
# Admin queue
# ---------------------------------------------------------------------------


@login_required
def admin_queue(request: HttpRequest) -> HttpResponse:
    """Maintainer review queue — rules sorted by signal density."""
    if not is_admin(request.user):
        return HttpResponseForbidden("Admin role required.")

    qs = (
        EngineRule.objects.filter(is_active=True)
        .select_related("master")
        .annotate(
            reject_count=Count(
                "responses", filter=Q(responses__verdict=Verdict.REJECT),
            ),
            close_but_count=Count(
                "responses", filter=Q(responses__verdict=Verdict.CLOSE_BUT),
            ),
            comment_count=Count(
                "comments",
                filter=Q(comments__deleted_at__isnull=True),
                distinct=True,
            ),
        )
        .filter(
            Q(reject_count__gt=0)
            | Q(close_but_count__gt=0)
            | Q(comment_count__gt=0)
        )
        .order_by("-reject_count", "-close_but_count", "-comment_count")
    )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "rule_review/admin_queue.html", {
        "page_obj": page_obj,
    })


# ---------------------------------------------------------------------------
# Comment thread CRUD
# ---------------------------------------------------------------------------


@login_required
@require_POST
def add_rule_comment(request: HttpRequest) -> HttpResponse:
    if not is_pedagogue(request.user) and not is_admin(request.user):
        return HttpResponseForbidden(
            "Only pedagogues + admins may post rule comments."
        )

    rule_id = (request.POST.get("rule_id") or "").strip()
    body = (request.POST.get("body") or "").strip()
    parent_id_raw = (request.POST.get("parent_id") or "").strip()

    if not rule_id or not body:
        messages.error(request, "rule_id and body required")
        return redirect("rule_review:rule_list")

    rule = get_object_or_404(EngineRule, pk=rule_id)
    parent = None
    if parent_id_raw:
        parent = RuleComment.objects.filter(
            pk=parent_id_raw, rule=rule,
        ).first()

    RuleComment.objects.create(
        rule=rule, author=request.user, body=body, parent=parent,
    )
    return redirect("rule_review:rule_detail", pk=rule.pk)


@login_required
@require_POST
def delete_rule_comment(
    request: HttpRequest, comment_pk: int,
) -> HttpResponse:
    """Soft-delete. Author may delete own; Admin may delete any."""
    comment = get_object_or_404(RuleComment, pk=comment_pk)
    is_author = comment.author_id == request.user.pk
    if not (is_author or is_admin(request.user)):
        return HttpResponseForbidden("You can't delete this comment.")

    if comment.deleted_at is None:
        comment.deleted_at = timezone.now()
        comment.save(update_fields=["deleted_at"])
    return redirect("rule_review:rule_detail", pk=comment.rule_id)


@login_required
@require_POST
def edit_rule_comment(
    request: HttpRequest, comment_pk: int,
) -> HttpResponse:
    """Edit body. Author-only. Refuses deleted (410)."""
    comment = get_object_or_404(RuleComment, pk=comment_pk)
    if comment.author_id != request.user.pk:
        return HttpResponseForbidden("You can only edit your own comment.")
    if comment.deleted_at is not None:
        return HttpResponseGone("Comment is deleted.")

    body = (request.POST.get("body") or "").strip()
    if not body:
        messages.error(request, "comment can't be empty")
        return redirect("rule_review:rule_detail", pk=comment.rule_id)

    comment.body = body
    comment.edited_at = timezone.now()
    comment.save(update_fields=["body", "edited_at"])
    return redirect("rule_review:rule_detail", pk=comment.rule_id)


# ---------------------------------------------------------------------------
# Rule library — read-only browse mirroring the locked formatter contract.
# Engine agent shipped the contract in musescore4-chord-library-plugin
# `ExplanationFormatter.js::_formatRule(rule)` per #586; ellington-web#167
# bookmarks the canonical reference. This view is the live Django consumer.
# ---------------------------------------------------------------------------


def _rule_to_token(rule: EngineRule) -> dict:
    """Render an EngineRule into the locked formatter token shape.

    Mirrors the plugin agent's ``_formatRule(rule)`` output exactly so the
    field set is identical across plugin (QML) and ellington (Django
    template) renders. Fields the model doesn't yet carry
    (``chapter_n`` / ``section_title``) are reserved-for-v2; templates
    treat ``None`` as absent.
    """
    return {
        "source": "rule",
        "id": rule.pk,
        "payload": {
            "rule_id": rule.rule_id,
            "master_id": rule.master.slug if rule.master_id else None,
            "master_name": rule.master.name if rule.master_id else "(unassigned)",
            "work_id": rule.work_id,
            "name": rule.name,
            "anchor": rule.anchor or None,
            "source_page": rule.source_page,
            # Ellington-only enrichment; not in v1 contract — engine #550
            # may add a source_locator sub-object in v2.
            "source_pdf_filename": rule.source_pdf_filename or None,
            # Reserved-for-v2 contract fields not yet on the model
            "chapter_n": None,
            "section_title": None,
            "preference": rule.preference,
            "polarity": rule.polarity,
            "quality_binding": list(rule.quality_binding or []),
            "applicability_reasons": list(rule.applicability_reasons or []),
            "falsifier": rule.falsifier or None,
        },
    }


@login_required
def rule_library(request: HttpRequest) -> HttpResponse:
    """Read-only browse of the active engine_rules corpus.

    Groups by master, then by work_id within master, then ordered by
    rule_id. Supports ``?master=<slug>`` to filter to a single master
    and ``?q=<term>`` to substring-match on name / anchor / falsifier.

    The verdict-collection workflow lives at ``rule_list`` /
    ``rule_detail`` — the library exists alongside it as the corpus-
    facing surface.
    """
    qs = (
        EngineRule.objects.filter(is_active=True)
        .select_related("master", "bundle")
        .order_by("master__slug", "work_id", "rule_id")
    )

    master_slug = (request.GET.get("master") or "").strip()
    if master_slug:
        qs = qs.filter(master__slug=master_slug)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(anchor__icontains=q)
            | Q(falsifier__icontains=q)
        )

    rules = list(qs)
    total_rules = len(rules)

    # Group by master, then by work_id. OrderedDict so the template
    # iterates in the qs's order (master__slug ASC) without further sort.
    masters: "OrderedDict[str, dict]" = OrderedDict()
    for master_key, master_rules in groupby(
        rules, key=lambda r: r.master.slug if r.master_id else "__unassigned__"
    ):
        master_rules = list(master_rules)
        first = master_rules[0]
        works: "OrderedDict[str, list]" = OrderedDict()
        for work_id, work_rules in groupby(master_rules, key=lambda r: r.work_id):
            works[work_id] = [_rule_to_token(r) for r in work_rules]
        masters[master_key] = {
            "slug": master_key,
            "name": (
                first.master.name if first.master_id else "(unassigned)"
            ),
            "count": len(master_rules),
            "works": works,
        }

    # When a master filter is active, default the <details> open for the
    # match; otherwise collapse all to keep the page lean across 11+
    # masters / 768 rules.
    default_open = bool(master_slug or q)

    return render(request, "rule_review/rule_library.html", {
        "masters": masters,
        "total_rules": total_rules,
        "filter_master": master_slug,
        "filter_q": q,
        "default_open": default_open,
    })


# ---------------------------------------------------------------------------
# Confirmation queue — admin batch triage of PedagogueConfirmation signal
# (#186 Phase 3). Mirror of admin_queue but built on confirmations, not
# verdicts. Surfaces aggregate signal for editorial decisions at scale.
# ---------------------------------------------------------------------------


CONFIRMATION_SORT_CHOICES = {
    "lowest_confidence",
    "most_voicing_disagreement",
    "most_naming_disagreement",
    "most_lesson_disagreement",
    "most_confirmations",
}


@login_required
def confirmation_queue(request: HttpRequest) -> HttpResponse:
    """Admin batch triage of pedagogue confirmation signal.

    Surfaces rules ordered by various confirmation-density metrics so
    the maintainer can pick which rules to re-investigate without
    clicking into each one. Per #186 Phase 3.
    """
    if not is_admin(request.user):
        return HttpResponseForbidden("Admin role required.")

    qs = (
        EngineRule.objects.filter(is_active=True)
        .select_related("master")
        .annotate(
            confirmation_count=Count("confirmations", distinct=True),
            voicing_yes=Count(
                "confirmations",
                filter=Q(confirmations__voicing_confirmed=True),
                distinct=True,
            ),
            voicing_no=Count(
                "confirmations",
                filter=Q(confirmations__voicing_confirmed=False),
                distinct=True,
            ),
            naming_yes=Count(
                "confirmations",
                filter=Q(confirmations__naming_confirmed=True),
                distinct=True,
            ),
            naming_no=Count(
                "confirmations",
                filter=Q(confirmations__naming_confirmed=False),
                distinct=True,
            ),
            lesson_yes=Count(
                "confirmations",
                filter=Q(confirmations__lesson_confirmed=True),
                distinct=True,
            ),
            lesson_no=Count(
                "confirmations",
                filter=Q(confirmations__lesson_confirmed=False),
                distinct=True,
            ),
            avg_confidence=Avg("confirmations__overall_confidence"),
        )
        .filter(confirmation_count__gt=0)
    )

    master_slug = (request.GET.get("master") or "").strip()
    if master_slug:
        qs = qs.filter(master__slug=master_slug)

    axis = (request.GET.get("axis") or "").strip()
    if axis == "voicing":
        qs = qs.filter(Q(voicing_yes__gt=0) | Q(voicing_no__gt=0))
    elif axis == "naming":
        qs = qs.filter(Q(naming_yes__gt=0) | Q(naming_no__gt=0))
    elif axis == "lesson":
        qs = qs.filter(Q(lesson_yes__gt=0) | Q(lesson_no__gt=0))

    sort = (request.GET.get("sort") or "lowest_confidence").strip()
    if sort not in CONFIRMATION_SORT_CHOICES:
        sort = "lowest_confidence"

    if sort == "lowest_confidence":
        qs = qs.order_by(F("avg_confidence").asc(nulls_last=True), "rule_id")
    elif sort == "most_voicing_disagreement":
        qs = qs.filter(voicing_yes__gt=0, voicing_no__gt=0).annotate(
            voicing_total=F("voicing_yes") + F("voicing_no"),
        ).order_by("-voicing_total", "rule_id")
    elif sort == "most_naming_disagreement":
        qs = qs.filter(naming_yes__gt=0, naming_no__gt=0).annotate(
            naming_total=F("naming_yes") + F("naming_no"),
        ).order_by("-naming_total", "rule_id")
    elif sort == "most_lesson_disagreement":
        qs = qs.filter(lesson_yes__gt=0, lesson_no__gt=0).annotate(
            lesson_total=F("lesson_yes") + F("lesson_no"),
        ).order_by("-lesson_total", "rule_id")
    elif sort == "most_confirmations":
        qs = qs.order_by("-confirmation_count", "rule_id")

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "rule_review/confirmation_queue.html", {
        "page_obj": page_obj,
        "filter_master": master_slug,
        "filter_axis": axis,
        "filter_sort": sort,
        "sort_choices": sorted(CONFIRMATION_SORT_CHOICES),
    })
