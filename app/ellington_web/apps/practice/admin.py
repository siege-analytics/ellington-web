from django.contrib import admin

from .models import (
    AudioStem,
    BackingTrack,
    ChordDetection,
    Invite,
    PracticeSegment,
    PracticeSession,
    Recording,
    RecordingComment,
    RecordingCommentAcknowledgement,
    RecordingShare,
    Studio,
    StudioMember,
    TeacherStudent,
)


@admin.register(BackingTrack)
class BackingTrackAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "source", "style", "idiom", "song", "tempo_bpm", "key")
    list_filter = ("source", "style", "idiom")
    search_fields = ("slug", "title", "audio_ref")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    raw_id_fields = ("style", "idiom", "song")


class RecordingInline(admin.TabularInline):
    model = Recording
    extra = 0
    fields = ("file_ref", "duration_ms", "sample_rate_hz", "started_at")
    readonly_fields = ("started_at",)
    show_change_link = True


class SegmentInline(admin.TabularInline):
    model = PracticeSegment
    extra = 0
    fields = ("start_ms", "end_ms", "recording", "critique", "label")
    raw_id_fields = ("recording", "critique")
    show_change_link = True


@admin.register(PracticeSession)
class PracticeSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "target_preset",
        "backing_track",
        "song",
        "status",
        "started_at",
        "ended_at",
    )
    list_filter = ("status", "started_at", "target_preset", "backing_track")
    search_fields = (
        "user__username",
        "target_preset__slug",
        "backing_track__slug",
        "song__slug",
    )
    readonly_fields = ("started_at",)
    raw_id_fields = ("user", "target_preset", "backing_track", "song")
    inlines = [RecordingInline, SegmentInline]


class AudioStemInline(admin.TabularInline):
    model = AudioStem
    extra = 0
    fields = ("stem_type", "file_ref", "separation_model_ref")


class ChordDetectionInline(admin.TabularInline):
    model = ChordDetection
    extra = 0
    fields = (
        "beat_timestamp_ms",
        "detected_chord_symbol",
        "confidence",
        "voicing_style_tags",
        "detection_model_ref",
    )


@admin.register(Recording)
class RecordingAdmin(admin.ModelAdmin):
    list_display = ("session", "file_ref", "duration_ms", "sample_rate_hz", "channels", "started_at")
    list_filter = ("session__user", "started_at")
    search_fields = ("file_ref", "session__user__username")
    readonly_fields = ("started_at",)
    raw_id_fields = ("session",)
    inlines = [AudioStemInline, ChordDetectionInline]


@admin.register(AudioStem)
class AudioStemAdmin(admin.ModelAdmin):
    list_display = ("recording", "stem_type", "file_ref", "separation_model_ref", "created_at")
    list_filter = ("stem_type", "separation_model_ref")
    raw_id_fields = ("recording",)


@admin.register(ChordDetection)
class ChordDetectionAdmin(admin.ModelAdmin):
    list_display = (
        "recording",
        "beat_timestamp_ms",
        "detected_chord_symbol",
        "confidence",
        "detection_model_ref",
    )
    list_filter = ("detection_model_ref",)
    search_fields = ("detected_chord_symbol",)
    raw_id_fields = ("recording",)


@admin.register(PracticeSegment)
class PracticeSegmentAdmin(admin.ModelAdmin):
    list_display = ("session", "start_ms", "end_ms", "recording", "critique", "label")
    raw_id_fields = ("session", "recording", "critique")


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("email", "inviter", "created_at", "expires_at", "accepted_at", "redeemed_by")
    list_filter = ("accepted_at",)
    search_fields = ("email", "name_hint", "inviter__username")
    readonly_fields = ("token", "created_at", "accepted_at", "redeemed_by")
    raw_id_fields = ("inviter",)


@admin.register(RecordingShare)
class RecordingShareAdmin(admin.ModelAdmin):
    list_display = ("recording", "sharer", "recipient", "invite", "shared_at")
    list_filter = ("shared_at",)
    search_fields = ("sharer__username", "recipient__username")
    readonly_fields = ("shared_at",)
    raw_id_fields = ("recording", "sharer", "recipient", "invite")


@admin.register(RecordingComment)
class RecordingCommentAdmin(admin.ModelAdmin):
    list_display = ("recording", "author", "anchor_ms", "is_deleted", "created_at")
    list_filter = ("deleted_at", "created_at")
    search_fields = ("body", "author__username")
    readonly_fields = ("created_at", "edited_at", "deleted_at")
    raw_id_fields = ("recording", "author", "parent")

    @admin.display(boolean=True, description="deleted")
    def is_deleted(self, obj):
        return obj.deleted_at is not None


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "owner", "visibility", "created_at")
    list_filter = ("visibility",)
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("owner",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(StudioMember)
class StudioMemberAdmin(admin.ModelAdmin):
    list_display = ("studio", "user", "role", "invited_by", "joined_at")
    list_filter = ("role",)
    search_fields = ("studio__slug", "user__username")
    readonly_fields = ("joined_at",)
    raw_id_fields = ("studio", "user", "invited_by")


@admin.register(TeacherStudent)
class TeacherStudentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "student", "studio", "created_at", "ended_at")
    list_filter = ("ended_at",)
    search_fields = ("teacher__username", "student__username")
    readonly_fields = ("created_at",)
    raw_id_fields = ("teacher", "student", "studio")


@admin.register(RecordingCommentAcknowledgement)
class RecordingCommentAcknowledgementAdmin(admin.ModelAdmin):
    list_display = ("comment", "acknowledged_by", "acknowledged_at")
    search_fields = ("acknowledged_by__username", "note")
    readonly_fields = ("acknowledged_at",)
    raw_id_fields = ("comment", "acknowledged_by")
