"""Core models — User-extending profile + Goals + role + deletion-audit.

Lives at the top of apps/core/ so Django's makemigrations discovers it
automatically. Sub-modules (auth/, profile/, management/) hold the
non-model code organized by concern.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models


# Username of the sentinel "deleted user" — comments and engine-rule
# Responses re-FK to this row on account deletion so threads and
# ground-truth verdicts survive. Sentinel is created lazily on first
# call to ``get_or_create_deleted_user_sentinel()``.
DELETED_USER_USERNAME = "__deleted__"


def get_or_create_deleted_user_sentinel():
    """Return the singleton sentinel user used to anchor anonymized FKs.

    Idempotent. Sentinel is marked inactive + has an unusable password
    so it cannot log in; admins should not edit it manually.
    """
    User = get_user_model()
    sentinel, created = User.objects.get_or_create(
        username=DELETED_USER_USERNAME,
        defaults={
            "is_active": False,
            "first_name": "deleted",
            "last_name": "user",
        },
    )
    if created:
        sentinel.set_unusable_password()
        sentinel.save(update_fields=["password"])
    return sentinel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Instrument(models.TextChoices):
    GUITAR = "guitar", "Guitar"
    BASS = "bass", "Bass guitar"
    PIANO = "piano", "Piano"
    SAX = "sax", "Saxophone"
    TRUMPET = "trumpet", "Trumpet"
    DRUMS = "drums", "Drums"
    VOCALS = "vocals", "Voice"
    OTHER = "other", "Other"


class SkillLevel(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"
    PROFESSIONAL = "professional", "Professional"


class GoalStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ACHIEVED = "achieved", "Achieved"
    ABANDONED = "abandoned", "Abandoned"


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------


class UserProfile(models.Model):
    """Per-user preferences + profile metadata. Created lazily — a user
    can exist without a profile (e.g. the bootstrap dheeraj superuser),
    and the profile is created on first ``manage.py shell`` or admin
    interaction.

    All preference M2Ms are nullable (empty M2M is valid). The
    comparator's eventual default-suggestion mode will read these to
    pre-fill StylePreset dropdowns; absence means 'no opinions'.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    display_name = models.CharField(
        max_length=128,
        blank=True,
        help_text="Optional override for user.first_name + last_name.",
    )

    instrument = models.CharField(
        max_length=16,
        choices=Instrument.choices,
        default=Instrument.GUITAR,
    )
    skill_level = models.CharField(
        max_length=16,
        choices=SkillLevel.choices,
        default=SkillLevel.INTERMEDIATE,
    )

    preferred_styles = models.ManyToManyField(
        "styles.Style",
        blank=True,
        related_name="preferring_users",
    )
    preferred_idioms = models.ManyToManyField(
        "styles.Idiom",
        blank=True,
        related_name="preferring_users",
    )
    preferred_masters = models.ManyToManyField(
        "styles.Master",
        blank=True,
        related_name="preferring_users",
    )

    bio = models.TextField(blank=True)
    timezone = models.CharField(
        max_length=64,
        blank=True,
        default="UTC",
        help_text="IANA TZ identifier (e.g. 'America/Chicago').",
    )

    # Stackable side-role per epic #96. Admin = User.is_staff. General
    # user = absence of both. Indexed because #98's pedagogue-scoped
    # queries (response form, per-rule analytics) filter on this.
    is_pedagogue = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Stackable role: submit engine-rule confirmations,"
        " comment on charts/voicings, author Master commentary. Set"
        " by admin via Grappelli (gated in UserProfileAdmin).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"UserProfile({self.user.username})"


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------


class Goal(models.Model):
    """A user-stated practice target. Decoupled from PracticeSession —
    a user can set goals without ever practicing, and a practice
    session doesn't need to attach to a goal.

    All three target axes optional. A goal can be 'learn jazz' (style
    only) or 'sound like Joe Pass on chord-melody' (master + idiom)
    or anything in between.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="goals",
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    target_style = models.ForeignKey(
        "styles.Style",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeting_goals",
    )
    target_idiom = models.ForeignKey(
        "styles.Idiom",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeting_goals",
    )
    target_master = models.ForeignKey(
        "styles.Master",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeting_goals",
    )

    target_completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=GoalStatus.choices,
        default=GoalStatus.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Goal({self.user.username}: {self.title[:40]!r})"


# ---------------------------------------------------------------------------
# AccountDeletionAudit
# ---------------------------------------------------------------------------


class AccountDeletionAudit(models.Model):
    """One row per account-deletion event. Populated by the
    ``delete_user_account`` management command (admin-initiated) and
    by the self-service ``/accounts/delete/`` view (self-initiated).

    The deleted user's row is gone by the time this is written, so we
    keep a denormalized ``deleted_username`` + ``initiated_by_username``
    text snapshot. ``deleted_by`` FK is nullable + SET_NULL because in
    the self-service path the initiator IS the user being deleted —
    PROTECT would block the User.delete() call. Admin-initiated paths
    keep deleted_by set to the still-alive admin row.
    """

    deleted_username = models.CharField(
        max_length=150,
        help_text="Denormalized — auth.User row is gone by the time"
        " this is written.",
    )
    initiated_by_username = models.CharField(
        max_length=150,
        blank=True,
        help_text="Denormalized snapshot of who initiated the deletion."
        " For self-delete this equals deleted_username; for"
        " admin-initiated it's the admin's username.",
    )
    deleted_at = models.DateTimeField(auto_now_add=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="account_deletions_initiated",
        help_text="Admin who initiated the deletion. Null when the"
        " user deleted themselves (the FK would point at the now-gone"
        " row); see initiated_by_username for the text snapshot.",
    )
    anonymized_artifact_counts = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-artifact counts: how many Comments/Responses"
        " were repointed to the sentinel, how many Goals/Recordings"
        " were hard-deleted. Shape: {'goals_deleted': N,"
        " 'recordings_deleted': N, 'comments_anonymized': N, ...}",
    )

    class Meta:
        ordering = ["-deleted_at"]

    def __str__(self) -> str:
        return f"AccountDeletionAudit({self.deleted_username} @ {self.deleted_at:%Y-%m-%d})"


# ---------------------------------------------------------------------------
# Follow (epic #96 sub-ticket h / #122)
# ---------------------------------------------------------------------------


class Follow(models.Model):
    """One-directional follow.

    ``follower`` follows ``followed``. No reciprocity required. Self-
    follow rejected at the model layer via the
    ``follow_no_self_follow`` constraint.

    PROTECT on both FKs so the follow audit trail survives via the
    sentinel-user anonymize path. Deletion of either side via
    `delete_user_account` repoints both ends through the sentinel.
    """

    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="following",
        help_text="The user doing the following.",
    )
    followed = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="followers",
        help_text="The user being followed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["follower", "followed"],
                name="follow_follower_followed_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("followed")),
                name="follow_no_self_follow",
            ),
        ]
        indexes = [
            models.Index(
                fields=["followed", "-created_at"],
                name="follow_followed_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Follow({self.follower_id} → {self.followed_id})"


# ---------------------------------------------------------------------------
# DirectMessage (epic #96 sub-ticket g / #124)
# ---------------------------------------------------------------------------


class DirectMessage(models.Model):
    """1:1 message between two users. Plain text v1.

    PROTECT on both FKs so deletion-via-sentinel keeps the message
    visible to the surviving participant. Read receipt (`read_at`)
    captured when the recipient opens the thread.
    """

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dms_sent",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dms_received",
    )
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["sent_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(sender=models.F("recipient")),
                name="dm_no_self_send",
            ),
        ]
        indexes = [
            models.Index(
                fields=["sender", "recipient", "sent_at"],
                name="dm_pair_chrono_idx",
            ),
            models.Index(
                fields=["recipient", "read_at"],
                name="dm_recipient_unread_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"DirectMessage({self.sender_id} → {self.recipient_id} @ {self.sent_at:%Y-%m-%d %H:%M})"
