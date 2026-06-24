"""Custom Wagtail StreamField blocks (#200).

Exposes Django corpus data (EngineRule, future: Voicing, Master) into
Wagtail StreamField via the **locked formatter contract** from plugin
#586: ``{source, id, payload}``. Editor picks an ID; the block renders
via the same code path the rule_library view uses, so a prose-embedded
card and a library card are pixel-identical and can't drift.

Phase 1 (#200): ``EngineRuleReferenceBlock``. Phase 2 will add
``VoicingReferenceBlock`` once apps.voicings (#188) lands on develop.
"""

from __future__ import annotations

from django.utils.safestring import SafeString
from wagtail import blocks


class EngineRuleReferenceBlock(blocks.StructBlock):
    """Reference one EngineRule by its rule_id.

    The block stores only the ``rule_id`` string. At render time, the
    template (engine_rule_reference.html) looks up the live
    ``EngineRule`` row and renders via the locked formatter token
    shape — single source of truth, no editorial duplication.
    """

    rule_id = blocks.CharBlock(
        max_length=128,
        help_text="EngineRule.rule_id (e.g. ``joe-pass-r-001``). "
        "Picks the rule by its plugin-canonical ID, not its DB pk, so "
        "re-syncing the bundle preserves the reference.",
    )
    show_anchor = blocks.BooleanBlock(
        required=False,
        default=True,
        help_text="If checked, render the rule's anchor quote alongside "
        "the name + preference. Off = compact one-liner card.",
    )

    class Meta:
        icon = "link"
        label = "Engine rule reference"
        template = "cms/blocks/engine_rule_reference.html"

    def get_context(self, value, parent_context=None) -> dict:
        """Resolve the rule_id to a token at render time.

        Falls back gracefully when the rule is missing / inactive so a
        deleted rule doesn't crash the page render — the block emits
        a "(rule unavailable)" marker that editors can spot and fix.
        """
        context = super().get_context(value, parent_context=parent_context)
        rule_id = value.get("rule_id", "").strip()

        # Local import to avoid AppConfig load-order issues — blocks.py
        # is imported during Wagtail's StreamField unmarshal which runs
        # before some app registries.
        from apps.engine_rules.models import EngineRule
        from apps.rule_review.views import _rule_to_token

        rule = (
            EngineRule.objects
            .filter(rule_id=rule_id, is_active=True)
            .select_related("master")
            .first()
        )

        if rule is None:
            context["token"] = None
            context["unavailable_rule_id"] = rule_id
        else:
            context["token"] = _rule_to_token(rule)
        context["show_anchor"] = value.get("show_anchor", True)
        return context


__all__ = ["EngineRuleReferenceBlock"]
