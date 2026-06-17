"""Admin registration for engine-rules data layer.

Read-only on every orchestrator-managed field — the EngineRule rows
are populated exclusively by ``sync_engine_rules`` from plugin
bundles. Hand-editing in admin would break the
RuleFire→EngineRule join's reproducibility guarantee.
"""

from django.contrib import admin

from .models import EngineRule, EngineRulesBundle


@admin.register(EngineRulesBundle)
class EngineRulesBundleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "bundle_version",
        "schema_version",
        "plugin_commit_sha",
        "total_rules",
        "built_at",
        "imported_at",
    )
    search_fields = ("bundle_version", "plugin_commit_sha")
    list_filter = ("schema_version",)
    readonly_fields = (
        "bundle_version",
        "schema_version",
        "plugin_commit_sha",
        "built_at",
        "total_rules",
        "manifest",
        "imported_at",
    )


@admin.register(EngineRule)
class EngineRuleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "master",
        "work_id",
        "rule_id",
        "name",
        "preference",
        "is_active",
        "bundle",
    )
    list_filter = ("is_active", "master", "preference")
    search_fields = ("rule_id", "name", "work_id", "anchor")
    readonly_fields = (
        "bundle",
        "master",
        "work_id",
        "rule_id",
        "name",
        "preference",
        "quality_binding",
        "applicability_reasons",
        "when_predicate",
        "then_action",
        "falsifier",
        "anchor",
        "source_page",
        "is_active",
        "imported_at",
    )
