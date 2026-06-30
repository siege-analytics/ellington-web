"""Voicings browse + detail views (#186 Phase 2).

Read-only. Filterable by ``?quality=``, ``?category=``, ``?root=``.
Pedagogues use the browse to verify what the plugin recommends for
a given chord quality; Phase 2b/3 will inline this into the
``rule_review`` confirmation form.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from .fretboard import render_svg
from .models import Voicing


def _filtered_voicings(request: HttpRequest):
    qs = Voicing.objects.filter(is_active=True).select_related("bundle")
    quality = request.GET.get("quality", "").strip()
    if quality:
        qs = qs.filter(chord_quality=quality)
    category = request.GET.get("category", "").strip()
    if category:
        qs = qs.filter(category=category)
    root = request.GET.get("root", "").strip()
    if root:
        qs = qs.filter(root=root)
    return qs, quality, category, root


@login_required
def voicing_list(request: HttpRequest) -> HttpResponse:
    qs, quality, category, root = _filtered_voicings(request)
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    qualities = (
        Voicing.objects.filter(is_active=True)
        .values_list("chord_quality", flat=True)
        .distinct()
        .order_by("chord_quality")
    )
    categories = (
        Voicing.objects.filter(is_active=True)
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )

    for v in page_obj.object_list:
        v.svg = render_svg(
            strings=v.strings,
            fret_number=v.fret_number,
            visible_frets=v.visible_frets,
            dots=v.dots,
            mutes=v.mutes,
            open_strings=v.open_strings,
        )

    return render(request, "voicings/voicing_list.html", {
        "page_obj": page_obj,
        "qualities": list(qualities),
        "categories": list(categories),
        "filter_quality": quality,
        "filter_category": category,
        "filter_root": root,
        "total_active": Voicing.objects.filter(is_active=True).count(),
    })


@login_required
def voicing_detail(request: HttpRequest, pk: int) -> HttpResponse:
    voicing = get_object_or_404(
        Voicing.objects.select_related("bundle"),
        pk=pk,
        is_active=True,
    )
    svg = render_svg(
        strings=voicing.strings,
        fret_number=voicing.fret_number,
        visible_frets=voicing.visible_frets,
        dots=voicing.dots,
        mutes=voicing.mutes,
        open_strings=voicing.open_strings,
        width=240,
        height=300,
    )
    return render(request, "voicings/voicing_detail.html", {
        "voicing": voicing,
        "svg": svg,
    })
