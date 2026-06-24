"""Admin registration for the voicings corpus (#186 Phase 2)."""

from __future__ import annotations

from django.contrib import admin

from .models import Voicing, VoicingBundle


@admin.register(VoicingBundle)
class VoicingBundleAdmin(admin.ModelAdmin):
    list_display = (
        "plugin_commit_sha",
        "is_active",
        "total_voicings",
        "built_at",
        "imported_at",
    )
    list_filter = ("is_active",)
    search_fields = ("plugin_commit_sha",)
    readonly_fields = ("imported_at",)


@admin.register(Voicing)
class VoicingAdmin(admin.ModelAdmin):
    list_display = (
        "voicing_id",
        "chord_quality",
        "category",
        "root",
        "fret_number",
        "is_active",
    )
    list_filter = ("chord_quality", "category", "is_active", "bundle")
    search_fields = ("voicing_id", "name", "chord_quality")
    raw_id_fields = ("bundle",)
