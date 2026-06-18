from django.contrib import admin

from .models import Response, RuleComment


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ("rule", "user", "verdict", "rejection_axis", "updated_at")
    list_filter = ("verdict", "rejection_axis", "updated_at")
    search_fields = ("user__username", "rule__rule_id", "comment")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("rule", "user")


@admin.register(RuleComment)
class RuleCommentAdmin(admin.ModelAdmin):
    list_display = ("rule", "author", "is_deleted", "created_at")
    list_filter = ("deleted_at", "created_at")
    search_fields = ("body", "author__username", "rule__rule_id")
    readonly_fields = ("created_at", "edited_at", "deleted_at")
    raw_id_fields = ("rule", "author", "parent")

    @admin.display(boolean=True, description="deleted")
    def is_deleted(self, obj):
        return obj.deleted_at is not None
