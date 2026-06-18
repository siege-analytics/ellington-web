"""Practice models — sessions, backing tracks, recordings, audio stems,
chord detections, and per-segment critiques.

Scaffolding only. The chain reflects how a practice loop will work in
production:

    PracticeSession (user picks a target_preset + an optional song)
      │
      ├── BackingTrack reference (the BIAB / iReal Pro audio under the user)
      │
      └── Recording (the user's audio coming in)
            │
            ├── AudioStem [sub-4 will write these — Demucs guitar/bass/drums split]
            │
            └── ChordDetection [sub-4 will write these — chord recognition output]

    PracticeSegment cuts a slice of the session for focused feedback. It
    ties together a Recording window + a ChordDetection batch + a
    Critique row (in apps.styles).

No consumer code writes any of these yet. sub-4 (audio pipeline) plugs
into ``Recording`` → emits ``AudioStem`` + ``ChordDetection``; sub-5
(LLM coach) reads the resulting Critique. This module gives them all
their landing pad.

File references are kept as opaque strings (``audio_ref``,
``file_ref``) instead of FileField/StorageObject because:
1. The storage layer is TBD (S3? in-cluster MinIO? local volume?)
2. We don't want to migrate the schema when storage rotates.
The string is meant to be a URL or a content-addressed digest — caller
decides.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BackingSource(models.TextChoices):
    BIAB = "biab", "Band-in-a-Box"
    IREAL_PRO = "ireal-pro", "iReal Pro"
    CUSTOM = "custom", "Custom (user-uploaded)"
    OTHER = "other", "Other"


class StemType(models.TextChoices):
    GUITAR = "guitar", "Guitar"
    BASS = "bass", "Bass"
    DRUMS = "drums", "Drums"
    VOCALS = "vocals", "Vocals"
    KEYS = "keys", "Keys"
    OTHER = "other", "Other"


class SessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ABANDONED = "abandoned", "Abandoned"


class AnalysisStatus(models.TextChoices):
    """Lifecycle of a Recording through the sub-4 audio pipeline.

    ``PENDING`` — created, not yet enqueued.
    ``QUEUED`` — Celery task ID is on Recording.analysis_task_id, worker
    hasn't picked it up yet.
    ``RUNNING`` — worker is currently analyzing.
    ``COMPLETE`` — ChordDetection rows are populated; comparator can run.
    ``FAILED`` — worker raised; details in Recording.notes.
    """

    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


# ---------------------------------------------------------------------------
# Backing track (the rhythm-section context the user plays against)
# ---------------------------------------------------------------------------


class BackingTrack(models.Model):
    slug = models.SlugField(unique=True, max_length=128)
    title = models.CharField(max_length=255)
    source = models.CharField(
        max_length=32,
        choices=BackingSource.choices,
        default=BackingSource.OTHER,
    )
    audio_ref = models.CharField(
        max_length=512,
        blank=True,
        help_text="Opaque storage reference (URL / digest). Storage layer TBD.",
    )

    # Stylistic tags so the comparator's "you said play bossa over gypsy
    # backing" framing works.
    style = models.ForeignKey(
        "styles.Style",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backing_tracks",
    )
    idiom = models.ForeignKey(
        "styles.Idiom",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backing_tracks",
    )

    # Which chart this backing track is voicing. Optional — a backing
    # track may be a generic "blues in F" without referencing a specific
    # Song row.
    song = models.ForeignKey(
        "charts.Song",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backing_tracks",
    )

    tempo_bpm = models.PositiveIntegerField(null=True, blank=True)
    key = models.CharField(max_length=8, blank=True)
    time_signature = models.CharField(max_length=8, blank=True, default="4/4")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"BackingTrack({self.slug})"


# ---------------------------------------------------------------------------
# Practice session — user + intent + backing context
# ---------------------------------------------------------------------------


class PracticeSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="practice_sessions",
    )
    song = models.ForeignKey(
        "charts.Song",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="practice_sessions",
        help_text="Optional — practice can be open-ended (no specific chart).",
    )

    # The user's stated target style. FK into apps.styles.StylePreset
    # so all three axes (master × style × idiom) are captured via one ref.
    target_preset = models.ForeignKey(
        "styles.StylePreset",
        on_delete=models.PROTECT,
        related_name="target_practice_sessions",
    )
    backing_track = models.ForeignKey(
        BackingTrack,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="practice_sessions",
    )

    # Per-session tempo override. Form collects this at create time;
    # comparator and (future) sub-4 alignment use it. When None, falls
    # back to ``song.default_tempo_bpm`` then to a system default — see
    # ``apps.charts.timeline.resolve_tempo``.
    tempo_bpm = models.PositiveIntegerField(null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=SessionStatus.choices,
        default=SessionStatus.ACTIVE,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return (
            f"PracticeSession(user={self.user_id}, "
            f"target={self.target_preset.slug}, status={self.status})"
        )


# ---------------------------------------------------------------------------
# Recording — the user's incoming audio
# ---------------------------------------------------------------------------


class Recording(models.Model):
    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    file_ref = models.CharField(
        max_length=512,
        help_text="Opaque storage reference for the raw audio file.",
    )
    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Populated when the recording is finalized.",
    )
    sample_rate_hz = models.PositiveIntegerField(null=True, blank=True)
    channels = models.PositiveSmallIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    # sub-4 audio pipeline lifecycle. PENDING on create; views auto-fire
    # the analyze_recording task which advances it through QUEUED ->
    # RUNNING -> COMPLETE (or FAILED). Manual re-analyze fires from
    # COMPLETE -> QUEUED again.
    analysis_status = models.CharField(
        max_length=16,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING,
        db_index=True,
    )
    analysis_task_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Celery task ID of the most-recent analyze_recording dispatch.",
    )
    analysis_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Recording(session={self.session_id}, ref={self.file_ref[:32]}…)"


# ---------------------------------------------------------------------------
# Sub-4 audio-pipeline outputs (scaffolding — sub-4 writes these later)
# ---------------------------------------------------------------------------


class AudioStem(models.Model):
    """A single source-separation stem output. sub-4 will write these via
    Demucs (or whatever the chosen separator ends up being). The
    ``separation_model_ref`` opaque string lets us A/B-compare different
    separators / model versions on the same Recording later.
    """

    recording = models.ForeignKey(
        Recording,
        on_delete=models.CASCADE,
        related_name="stems",
    )
    stem_type = models.CharField(
        max_length=16,
        choices=StemType.choices,
    )
    file_ref = models.CharField(max_length=512)
    separation_model_ref = models.CharField(
        max_length=128,
        blank=True,
        help_text=(
            "Opaque tag identifying the separator + version that produced "
            "this stem. e.g. 'demucs-htdemucs:v4', 'spleeter:5stems'."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recording", "stem_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["recording", "stem_type", "separation_model_ref"],
                name="unique_stem_per_recording_type_model",
            ),
        ]

    def __str__(self) -> str:
        return f"AudioStem({self.stem_type}@{self.recording_id})"


class ChordDetection(models.Model):
    """A single detected chord event with confidence. sub-4 will write
    these from CREPE / madmom / chordino / Essentia output (whichever
    landed in the pipeline). The ``voicing_style_tags`` JSONField lets
    the comparator consume directly from here.
    """

    recording = models.ForeignKey(
        Recording,
        on_delete=models.CASCADE,
        related_name="chord_detections",
    )
    beat_timestamp_ms = models.PositiveIntegerField(
        help_text="Offset from recording start in milliseconds.",
    )
    detected_chord_symbol = models.CharField(max_length=32)
    confidence = models.FloatField(
        help_text="0.0–1.0 detection confidence.",
    )

    # The bridge to apps.styles.comparator.DetectedVoicing — sub-4 fills
    # voicing_style_tags by joining detected pitches against the plugin's
    # voicings.json catalog.
    voicing_style_tags = models.JSONField(
        default=list,
        blank=True,
        help_text="List[str]. Empty when sub-4 can't map the detection to known tags.",
    )

    detection_model_ref = models.CharField(
        max_length=128,
        blank=True,
        help_text="Opaque tag identifying the recognizer + version.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recording", "beat_timestamp_ms"]
        indexes = [
            models.Index(fields=["recording", "beat_timestamp_ms"]),
        ]

    def __str__(self) -> str:
        return (
            f"ChordDetection({self.detected_chord_symbol}"
            f"@{self.beat_timestamp_ms}ms:conf={self.confidence:.2f})"
        )


# ---------------------------------------------------------------------------
# Per-segment critique tie-in
# ---------------------------------------------------------------------------


class PracticeSegment(models.Model):
    """A slice of a PracticeSession the user marked for focused feedback.

    Carries an optional FK to apps.styles.Critique so the comparator's
    output is anchored to a specific recording window. sub-D's smoke
    view creates a Critique without a PracticeSegment; the production
    loop creates segments and binds Critiques to them.
    """

    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name="segments",
    )
    recording = models.ForeignKey(
        Recording,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="segments",
    )
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()

    critique = models.ForeignKey(
        "styles.Critique",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="practice_segments",
        help_text="Optional — segments can exist before the comparator runs.",
    )
    label = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "start_ms"]

    def __str__(self) -> str:
        return f"PracticeSegment({self.session_id}:{self.start_ms}-{self.end_ms}ms)"


# ---------------------------------------------------------------------------
# Recording sharing + invite-a-friend (epic #96 sub-ticket b / #108)
# ---------------------------------------------------------------------------


class Invite(models.Model):
    """An invitation to join Ellington, attached to one or more
    pending RecordingShares.

    Created when a sharer enters the email of someone who's NOT yet
    in the system. The token URL is sent via email; clicking it leads
    to the signup form. On signup the invite is redeemed and any
    anchored RecordingShares are realized (recipient FK backfilled).

    Token is 256-bit URL-safe (``secrets.token_urlsafe(32)``).
    """

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="URL-safe random token. 256-bit entropy.",
    )
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invites_sent",
        help_text="Who sent the invite. PROTECT so audit history"
        " survives user deletion via the sentinel-user repoint.",
    )
    email = models.EmailField(
        help_text="Recipient email address — where the invite was sent.",
    )
    name_hint = models.CharField(
        max_length=128,
        blank=True,
        help_text="Optional display name for the recipient,"
        " used in the invite email body.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        help_text="Token expiry. Default 30 days from creation; set by"
        " the form layer, NOT by a model default, so the expiry window"
        " is visible at the call site.",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invites_redeemed",
        help_text="The User row created when the invite was accepted."
        " Null until then.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["email", "-created_at"],
                name="invite_email_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        state = "redeemed" if self.accepted_at else "pending"
        return f"Invite({self.email}:{state})"

    @property
    def is_redeemed(self) -> bool:
        return self.accepted_at is not None

    def is_expired(self, now=None) -> bool:
        """Return True if the invite's expiry is in the past."""
        from django.utils import timezone

        ref = now or timezone.now()
        return self.expires_at <= ref


class RecordingShare(models.Model):
    """One Recording shared by its owner with one recipient.

    Two paths:
    - ``recipient`` set + ``invite`` null → direct share with an
      existing user.
    - ``recipient`` null + ``invite`` set → pending share, materializes
      when the invitee signs up via the invite link.

    Both fields nullable; uniqueness is enforced at the form layer
    (one share per recording per recipient OR per pending invite-email).
    """

    recording = models.ForeignKey(
        "Recording",
        on_delete=models.CASCADE,
        related_name="shares",
    )
    sharer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recording_shares_sent",
        help_text="Who initiated the share. PROTECT — audit trail.",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="recording_shares_received",
        help_text="The User who can see the Recording. Null until an"
        " anchored Invite is redeemed; backfilled then. PROTECT so"
        " account deletion via the sentinel-user repoint preserves"
        " the share's audit shape.",
    )
    invite = models.ForeignKey(
        Invite,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="anchored_shares",
        help_text="The Invite this share is waiting on. Null once the"
        " invitee has signed up; recipient is set then.",
    )
    share_note = models.TextField(
        blank=True,
        help_text="Optional message the sharer attached.",
    )
    shared_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-shared_at"]
        indexes = [
            models.Index(
                fields=["recipient", "-shared_at"],
                name="recshare_recipient_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        if self.recipient_id:
            return f"RecordingShare(rec={self.recording_id} → user={self.recipient_id})"
        return f"RecordingShare(rec={self.recording_id} → pending invite={self.invite_id})"


# ---------------------------------------------------------------------------
# Comments on Recordings (epic #96 sub-ticket d / #110)
# ---------------------------------------------------------------------------


class RecordingComment(models.Model):
    """One comment anchored to a Recording.

    ``anchor_ms`` (offset from the start of the audio) is nullable —
    null means whole-recording comment. Threading via ``parent`` self-FK.
    Soft-delete preserves thread shape; deleted comments render as
    '[deleted]' inline.

    Permissions: a viewer can read/write comments on a Recording iff
    they're the Recording's owner OR a recipient of a RecordingShare
    for that Recording. The shared check lives in
    ``apps.practice.permissions.can_access_recording``.
    """

    recording = models.ForeignKey(
        "Recording",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recording_comments",
        help_text="Comment author. PROTECT — sentinel-anonymize on user"
        " delete via apps.core.delete_user_account.",
    )
    body = models.TextField(
        help_text="Plain-text comment body. Markdown / rich text is v2.",
    )
    anchor_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Time offset in the recording, in milliseconds."
        " Null = whole-recording comment.",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies",
        help_text="Parent comment for threading. Null = top-level.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set on author's first edit; sticky after that.",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Soft-delete marker. When set, body is redacted and"
        " the comment renders as '[deleted]'. Setting preserves thread"
        " shape so replies still anchor.",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["recording", "created_at"],
                name="reccomment_rec_chrono_idx",
            ),
        ]

    def __str__(self) -> str:
        marker = "(deleted) " if self.deleted_at else ""
        return f"RecordingComment({marker}{self.author_id} on rec={self.recording_id})"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def display_body(self) -> str:
        return "[deleted]" if self.is_deleted else self.body


# ---------------------------------------------------------------------------
# Studios (epic #96 sub-ticket f / #120)
# ---------------------------------------------------------------------------


class StudioVisibility(models.TextChoices):
    PRIVATE = "private", "Private (members only)"
    LINK_INVITE = "link_invite", "Link-invite (anyone with the URL can request to join)"
    PUBLIC = "public", "Public (browsable + joinable)"


class StudioRole(models.TextChoices):
    MEMBER = "member", "Member"
    MODERATOR = "moderator", "Moderator"
    BANNED = "banned", "Banned"


class Studio(models.Model):
    """A multi-user practice container — the digital equivalent of
    "Wednesday-night practice group with teacher Steve".

    Visibility controls discovery + join:
    - private: only listed members can see
    - link_invite: anyone with the URL can request to join
    - public: browsable + auto-join

    Owner is preserved on user delete via PROTECT — the studio
    doesn't disappear if the owner leaves the system. Ownership
    transfer is a v2 affordance.
    """

    slug = models.SlugField(
        max_length=64,
        unique=True,
        help_text="URL-safe identifier (lowercase, hyphens, no spaces).",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="studios_owned",
        help_text="The studio's founder + permanent owner."
        " PROTECT — owner row outlives the studio's existence.",
    )
    visibility = models.CharField(
        max_length=16,
        choices=StudioVisibility.choices,
        default=StudioVisibility.PRIVATE,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"Studio({self.slug})"


class StudioMember(models.Model):
    """One user's membership in one Studio.

    Roles: member (default), moderator (manage + invite), banned
    (kept on row so re-joining requires unban). Unique per (studio, user).
    """

    studio = models.ForeignKey(
        Studio,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="studio_memberships",
        help_text="The member. PROTECT — preserve audit trail for"
        " moderation history.",
    )
    role = models.CharField(
        max_length=16,
        choices=StudioRole.choices,
        default=StudioRole.MEMBER,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="studio_invites_issued",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["studio", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["studio", "user"],
                name="studiomember_studio_user_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "studio"], name="studiomember_user_idx"),
        ]

    def __str__(self) -> str:
        return f"StudioMember({self.studio_id}:{self.user_id}:{self.role})"


# ---------------------------------------------------------------------------
# Teacher / Student (epic #96 sub-ticket i / #126)
# ---------------------------------------------------------------------------


class TeacherStudent(models.Model):
    """One teacher → student relationship, optionally scoped to a Studio.

    A teacher can have many students; a student can have many teachers
    (e.g. main instrument + theory). The optional ``studio`` FK scopes
    the relationship to a specific practice group — when null, the
    relationship is global.

    ``ended_at`` retains the row after the relationship ends so historical
    acknowledgement audit survives. Unique constraint covers the
    active-row case; ended rows can re-appear with a new instance.
    """

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaches",
        help_text="The teacher in the relationship.",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="studies_with",
        help_text="The student being taught.",
    )
    studio = models.ForeignKey(
        Studio,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="teacher_student_relationships",
        help_text="Optional Studio scope. When set, the relationship"
        " is visible to other members of the Studio.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Active (non-ended) row per (teacher, student, studio)
            models.UniqueConstraint(
                fields=["teacher", "student", "studio"],
                condition=models.Q(ended_at__isnull=True),
                name="teacherstudent_active_unique",
            ),
            models.CheckConstraint(
                check=~models.Q(teacher=models.F("student")),
                name="teacherstudent_no_self_teach",
            ),
        ]
        indexes = [
            models.Index(
                fields=["student", "teacher"],
                name="teacherstudent_student_idx",
            ),
        ]

    def __str__(self) -> str:
        marker = "(ended)" if self.ended_at else ""
        return f"TeacherStudent({self.teacher_id}→{self.student_id}{marker})"

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class RecordingCommentAcknowledgement(models.Model):
    """Read receipt for a teacher's RecordingComment on their student's
    Recording.

    Required by sub-ticket (i): teacher comments can't be dismissed by
    the student until acknowledged. Tracked here rather than on the
    comment itself so future "acknowledge-with-note" expansion has a
    landing pad.
    """

    comment = models.ForeignKey(
        "RecordingComment",
        on_delete=models.CASCADE,
        related_name="acknowledgements",
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comment_acknowledgements",
        help_text="The student (or other recipient) confirming they read"
        " the teacher's comment.",
    )
    acknowledged_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(
        blank=True,
        help_text="Optional reply note. Distinct from a comment reply"
        " because it's an acknowledgement-with-context, not a thread"
        " contribution.",
    )

    class Meta:
        ordering = ["-acknowledged_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "acknowledged_by"],
                name="recordingcommentack_comment_user_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"RecordingCommentAcknowledgement(comment={self.comment_id} by={self.acknowledged_by_id})"
