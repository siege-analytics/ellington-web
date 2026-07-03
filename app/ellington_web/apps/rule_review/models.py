"""Rule-review models — focus-group v1 surface (epic #96 / #98).

Two models:

- ``Response`` — one pedagogue's verdict on one EngineRule. 3-state
  verdict + 6-state rejection_axis + free-text comment. Unique per
  (rule, user) — verdicts are revisable, not appendable.
- ``RuleComment`` — per-rule conversation thread. Threaded via parent
  self-FK, soft-deleted. Mirror of RecordingComment / ChartComment
  shape; the moderation perm differs (pedagogue OR admin can delete
  any comment in their rule context).

The methodology rationale lives on epic #96's revised proposal — n=5
focus group, not survey research. See the memory entry
``feedback_match_method_to_cohort.md`` if you find yourself adding
statistical machinery here; it doesn't earn its rent at this scale.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Verdict(models.TextChoices):
    """3-state verdict per the revised focus-group methodology."""

    ACCEPT = "accept", "Accept"
    CLOSE_BUT = "close_but", "Close but not quite"
    REJECT = "reject", "Reject"


class RejectionAxis(models.TextChoices):
    """Which axis of the rule failed. Only set when verdict != accept.

    Per the joint methodology consensus on #96. The plugin agent uses
    this to route corpus fixes — ~40% of rejections become 1-line
    corpus migrations when the axis is known.
    """

    WHEN = "when", "The 'when' predicate matches the wrong contexts"
    THEN = "then", "The 'then' action / voicing is wrong"
    PREFERENCE = "preference", "The signed Likert preference is miscalibrated"
    QUALITY_BINDING = "quality_binding", "The chord-quality binding is wrong"
    ANCHOR = "anchor", "The anchor quote doesn't support the rule"
    OVERALL = "overall", "The whole rule shouldn't exist"


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class Response(models.Model):
    """One pedagogue's verdict on one EngineRule.

    Unique per (rule, user) — revisable, not appendable. Updates to
    `comment` / `verdict` / `rejection_axis` overwrite the prior values;
    the comment thread (RuleComment) handles longitudinal discussion.

    Permission: only users with apps.core.roles.is_pedagogue may create.
    Admin (User.is_staff) sees all responses in the queue view.
    """

    rule = models.ForeignKey(
        "engine_rules.EngineRule",
        on_delete=models.CASCADE,
        related_name="responses",
        help_text="The rule being judged.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rule_responses",
        help_text="The pedagogue who responded. PROTECT — preserve"
        " ground-truth verdicts on user deletion via the sentinel-user"
        " anonymize path (apps.core.delete_user_account).",
    )

    verdict = models.CharField(
        max_length=16,
        choices=Verdict.choices,
        db_index=True,
        help_text="3-state verdict per the focus-group methodology.",
    )
    rejection_axis = models.CharField(
        max_length=32,
        choices=RejectionAxis.choices,
        blank=True,
        default="",
        help_text="Which axis of the rule failed. Only set when verdict"
        " != accept. Routes corpus fixes plugin-side.",
    )
    comment = models.TextField(
        blank=True,
        help_text="Free-text reasoning. The actual signal —"
        " maintainer reads every comment and makes corpus calls.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "user"],
                name="response_rule_user_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["rule", "verdict"],
                name="response_rule_verdict_idx",
            ),
            models.Index(
                fields=["user", "-updated_at"],
                name="response_user_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Response(rule={self.rule_id} user={self.user_id} {self.verdict})"


# ---------------------------------------------------------------------------
# RuleComment — per-rule conversation thread
# ---------------------------------------------------------------------------


class RuleComment(models.Model):
    """One comment in a per-rule conversation thread.

    Anyone with apps.core.roles.is_pedagogue OR Admin can read + write.
    Threading via ``parent`` self-FK. Soft-delete preserves thread
    shape; deleted comments render as "[deleted]".

    Moderation: author may delete own; Admin (is_staff) may delete any.
    Pedagogue-can-moderate-pedagogue is intentionally NOT a v1
    affordance — Dheeraj is the editorial gate, surfaced via the
    /rule-review/queue/ view.
    """

    rule = models.ForeignKey(
        "engine_rules.EngineRule",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rule_comments",
        help_text="Comment author. PROTECT — sentinel-anonymize on user"
        " delete.",
    )
    body = models.TextField()
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["rule", "created_at"],
                name="rulecomment_rule_chrono_idx",
            ),
        ]

    def __str__(self) -> str:
        marker = "(deleted) " if self.deleted_at else ""
        return f"RuleComment({marker}{self.author_id} on rule={self.rule_id})"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def display_body(self) -> str:
        return "[deleted]" if self.is_deleted else self.body


# ---------------------------------------------------------------------------
# PedagogueConfirmation — per-axis correctness signal (#186)
# ---------------------------------------------------------------------------


class PedagogueConfirmation(models.Model):
    """One pedagogue's per-axis correctness confirmation on one EngineRule.

    Parallel to ``Response`` (the verdict flow), capturing a DIFFERENT
    signal: not "accept/reject the rule as a whole" but "is the rule's
    voicing recommendation correct, is its quality-binding naming
    correct, is its anchor + falsifier sound as a pedagogical lesson?"

    The three axes are independent. A pedagogue may confirm the lesson
    is sound while flagging that the voicing recommendation feels off
    — that's signal corpus-distillation can't extract from a single-
    axis verdict.

    Unique per (rule, user); revisable via update_or_create, same edit
    semantics as Response. Pedagogue-only write (rule_review:rule_detail
    enforces); any signed-in user can read their own.

    Per ticket #186 Phase 1 — Phase 2 (voicings ingest + fretboard
    render) will give the voicing_confirmed checkbox a visual referent.
    """

    rule = models.ForeignKey(
        "engine_rules.EngineRule",
        on_delete=models.CASCADE,
        related_name="confirmations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rule_confirmations",
        help_text="The pedagogue who confirmed. PROTECT — sentinel-"
        "anonymize on user delete to preserve corpus signal.",
    )

    voicing_confirmed = models.BooleanField(
        default=False,
        help_text="Is the rule's then_action voicing recommendation"
        " correct for its quality_binding context?",
    )
    voicing_note = models.TextField(
        blank=True,
        help_text="Optional disagreement / clarification on the"
        " voicing axis. Empty when voicing_confirmed = True with no"
        " caveats.",
    )

    # Which specific voicing the pedagogue was looking at when they
    # confirmed. Null when the rule has no matching voicing in the
    # ingested corpus (schema-only confirmation) or when only one
    # candidate matched (no selection needed). Populated when >1
    # candidate matched and the pedagogue picked one. SET_NULL on
    # voicing delete so the confirmation signal survives corpus
    # rotation. Per #286.
    voicing = models.ForeignKey(
        "voicings.Voicing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Which candidate voicing this confirmation is pinned"
        " to. Nullable — no pin required when candidates == 0 or 1.",
    )

    naming_confirmed = models.BooleanField(
        default=False,
        help_text="Is the rule's quality_binding canonical token"
        " correctly classifying the chord context the rule is about?",
    )
    naming_note = models.TextField(blank=True)

    lesson_confirmed = models.BooleanField(
        default=False,
        help_text="Does the anchor quote faithfully support the rule"
        " and is the falsifier pedagogically sound?",
    )
    lesson_note = models.TextField(blank=True)

    overall_confidence = models.SmallIntegerField(
        null=True,
        blank=True,
        help_text="1-5 Likert: how sound is this rule as a complete"
        " pedagogical unit? Null = no opinion expressed.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "user"],
                name="pedagogueconfirmation_rule_user_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(overall_confidence__isnull=True)
                    | models.Q(overall_confidence__range=(1, 5))
                ),
                name="pedagogueconfirmation_confidence_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["rule", "voicing_confirmed",
                        "naming_confirmed", "lesson_confirmed"],
                name="pedconf_rule_axes_idx",
            ),
            models.Index(
                fields=["user", "-updated_at"],
                name="pedconf_user_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        axes = "".join([
            "V" if self.voicing_confirmed else "v",
            "N" if self.naming_confirmed else "n",
            "L" if self.lesson_confirmed else "l",
        ])
        return (
            f"PedagogueConfirmation(rule={self.rule_id} "
            f"user={self.user_id} [{axes}] conf={self.overall_confidence})"
        )


__all__ = [
    "PedagogueConfirmation",
    "RejectionAxis",
    "Response",
    "RuleComment",
    "Verdict",
]
