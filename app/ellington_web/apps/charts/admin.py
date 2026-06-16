from django.contrib import admin

from .models import (
    ChartImport,
    ChartImportStatus,
    ChordEvent,
    Measure,
    Section,
    Song,
    Songbook,
)


class SongInline(admin.TabularInline):
    model = Song
    extra = 0
    fields = ("slug", "title", "key", "form", "import_source")
    show_change_link = True


@admin.register(Songbook)
class SongbookAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "publisher", "year", "song_count", "updated_at")
    search_fields = ("slug", "title")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [SongInline]

    @admin.display(description="songs")
    def song_count(self, obj):
        return obj.songs.count()


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    fields = ("order_index", "label", "measure_count")
    show_change_link = True


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "title",
        "composer",
        "key",
        "time_signature",
        "form",
        "songbook",
        "import_source",
    )
    list_filter = ("import_source", "songbook", "key", "form")
    search_fields = ("slug", "title", "composer")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [SectionInline]


class MeasureInline(admin.TabularInline):
    model = Measure
    extra = 0
    fields = ("number_in_section", "time_signature_override", "repeat_marker")
    show_change_link = True


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("song", "label", "order_index", "measure_count")
    list_filter = ("song",)
    search_fields = ("label", "song__title", "song__slug")
    inlines = [MeasureInline]


class ChordEventInline(admin.TabularInline):
    model = ChordEvent
    extra = 0
    fields = ("beat", "chord_symbol", "duration_beats", "voicing_reference")


@admin.register(Measure)
class MeasureAdmin(admin.ModelAdmin):
    list_display = ("section", "number_in_section", "time_signature_override", "repeat_marker")
    list_filter = ("section__song",)
    inlines = [ChordEventInline]


@admin.register(ChordEvent)
class ChordEventAdmin(admin.ModelAdmin):
    list_display = ("measure", "beat", "chord_symbol", "duration_beats")
    list_filter = ("measure__section__song",)
    search_fields = ("chord_symbol",)


@admin.register(ChartImport)
class ChartImportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "source_songbook",
        "page_count",
        "pages_succeeded",
        "pages_failed",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "source_songbook")
    search_fields = ("file_ref", "user__username")
    # Every field the orchestrator writes is read-only in admin —
    # hand-editing a ChartImport's page-bookkeeping / error_log /
    # status mid-run would race the worker. Operators clear stuck
    # imports by deleting + re-uploading, not by editing.
    readonly_fields = (
        "created_at",
        "completed_at",
        "task_id",
        "file_ref",
        "status",
        "page_count",
        "pages_succeeded",
        "pages_failed",
        "error_log",
    )
