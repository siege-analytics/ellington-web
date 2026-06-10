from django.contrib import admin

from .models import (
    Critique,
    Idiom,
    Master,
    Style,
    StylePreset,
    StyleSelection,
)


class PlaceholderListFilter(admin.SimpleListFilter):
    """Surface the is_placeholder flag prominently in the admin list view —
    operators need to know which catalog rows still need real content.
    """

    title = "placeholder?"
    parameter_name = "placeholder"

    def lookups(self, request, model_admin):
        return (("yes", "placeholder"), ("no", "real"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_placeholder=True)
        if self.value() == "no":
            return queryset.filter(is_placeholder=False)
        return queryset


@admin.register(Master)
class MasterAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_placeholder", "schema_version", "updated_at")
    list_filter = (PlaceholderListFilter, "schema_version")
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Style)
class StyleAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_placeholder", "schema_version", "updated_at")
    list_filter = (PlaceholderListFilter, "schema_version")
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {"fields": ("slug", "name", "description", "schema_version", "is_placeholder")}),
        ("Structured profile", {
            "fields": (
                "voicing_style_tag_affinity",
                "rhythmic_signature",
                "harmonic_signature",
                "divergence_notes",
            ),
            "description": (
                "JSON fields. Shape is in flux while the plugin agent's "
                "distillation pass runs. See ticket #27 for the contract."
            ),
        }),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Idiom)
class IdiomAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_placeholder", "schema_version", "updated_at")
    list_filter = (PlaceholderListFilter, "schema_version")
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(StylePreset)
class StylePresetAdmin(admin.ModelAdmin):
    list_display = ("slug", "display_name", "axis_summary", "updated_at")
    search_fields = ("slug", "display_name")
    list_filter = ("master", "style", "idiom")
    readonly_fields = ("created_at", "updated_at", "axis_summary")
    prepopulated_fields = {"slug": ("display_name",)}
    fieldsets = (
        (None, {"fields": ("slug", "display_name", "description")}),
        ("Axes (at least one required)", {
            "fields": ("master", "style", "idiom"),
            "description": (
                "A preset composes zero or more of the three orthogonal "
                "axes. At least one MUST be set — full_clean() enforces "
                "this, but the admin shows the warning here."
            ),
        }),
        ("Audit", {"fields": ("axis_summary", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(StyleSelection)
class StyleSelectionAdmin(admin.ModelAdmin):
    list_display = ("user", "target_preset", "backing_preset", "started_at")
    list_filter = ("started_at",)
    search_fields = ("user__username", "target_preset__slug", "backing_preset__slug")
    readonly_fields = ("started_at",)
    raw_id_fields = ("user", "target_preset", "backing_preset")


@admin.register(Critique)
class CritiqueAdmin(admin.ModelAdmin):
    list_display = ("selection", "style_match_score", "audio_input_ref", "created_at")
    list_filter = ("created_at",)
    search_fields = ("selection__target_preset__slug", "audio_input_ref")
    readonly_fields = ("created_at",)
    raw_id_fields = ("selection",)
