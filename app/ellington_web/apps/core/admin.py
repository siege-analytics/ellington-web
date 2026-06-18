from django.contrib import admin

from .models import (
    AccountDeletionAudit,
    DirectMessage,
    Follow,
    Goal,
    UserProfile,
)


class GoalInline(admin.TabularInline):
    model = Goal
    extra = 0
    fields = ("title", "target_style", "target_idiom", "target_master", "status", "target_completion_date")
    raw_id_fields = ("target_style", "target_idiom", "target_master")
    show_change_link = True


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "instrument", "skill_level", "is_pedagogue", "timezone", "updated_at")
    list_filter = ("instrument", "skill_level", "is_pedagogue")
    search_fields = ("user__username", "user__email", "display_name")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("user",)
    filter_horizontal = ("preferred_styles", "preferred_idioms", "preferred_masters")

    def get_readonly_fields(self, request, obj=None):
        # is_pedagogue is staff-only — non-staff editors see it but
        # cannot toggle. is_staff staff (admin tier) can.
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_staff:
            ro.append("is_pedagogue")
        return ro


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "title",
        "target_style",
        "target_idiom",
        "target_master",
        "status",
        "target_completion_date",
    )
    list_filter = ("status", "target_style", "target_idiom")
    search_fields = ("user__username", "title", "description")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("user", "target_style", "target_idiom", "target_master")


@admin.register(AccountDeletionAudit)
class AccountDeletionAuditAdmin(admin.ModelAdmin):
    list_display = ("deleted_username", "deleted_by", "deleted_at")
    list_filter = ("deleted_by",)
    search_fields = ("deleted_username",)
    readonly_fields = ("deleted_username", "deleted_by", "deleted_at", "anonymized_artifact_counts")

    def has_add_permission(self, request):
        # Audit rows are only ever written by delete_user_account.
        return False

    def has_change_permission(self, request, obj=None):
        # Audit rows are immutable.
        return False


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "followed", "created_at")
    search_fields = ("follower__username", "followed__username")
    readonly_fields = ("created_at",)
    raw_id_fields = ("follower", "followed")


@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "recipient", "sent_at", "read_at")
    list_filter = ("sent_at", "read_at")
    search_fields = ("sender__username", "recipient__username", "body")
    readonly_fields = ("sent_at", "read_at")
    raw_id_fields = ("sender", "recipient")
