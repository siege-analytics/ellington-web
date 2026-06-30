"""Admin registration for SoundBank (#233)."""

from __future__ import annotations

from django.contrib import admin

from .models import SoundBank


@admin.register(SoundBank)
class SoundBankAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source_app",
        "format",
        "size_bytes",
        "is_active",
        "scanned_at",
    )
    list_filter = ("source_app", "format", "is_active")
    search_fields = ("name", "path", "sha256")
    readonly_fields = ("sha256", "size_bytes", "scanned_at")
