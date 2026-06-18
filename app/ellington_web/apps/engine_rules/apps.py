"""Engine-rules consumer-agnostic layer.

Hosts the EngineRule catalog (synced from the chord-library plugin's
GitHub Releases) and the firing engine that maps `LeadSheetSlice`
inputs to `RuleFireResult` outputs. Consumed by:

- `apps.rule_review` (#98) for the user-facing confirmation form
- `apps.styles` quantitative review (#71) for per-Master per-axis scoring
- future LLM coach (Phase 5 of #60) for prose generation
"""

from django.apps import AppConfig


class EngineRulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.engine_rules"
    verbose_name = "Engine rules"
