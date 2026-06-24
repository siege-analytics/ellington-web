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
from django.db.models import Count, Q
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

from .models import RejectionAxis, Response, RuleComment, Verdict


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

    return render(request, "rule_review/rule_detail.html", {
        "rule": rule,
        "my_response": my_response,
        "verdict_choices": Verdict.choices,
        "axis_choices": RejectionAxis.choices,
        "comments": comments,
        "counts": counts_map,
        "can_write": is_pedagogue(request.user) or is_admin(request.user),
    })


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
