from django.contrib import admin

from .models import Goal, UserProfile


class GoalInline(admin.TabularInline):
    model = Goal
    extra = 0
    fields = ("title", "target_style", "target_idiom", "target_master", "status", "target_completion_date")
    raw_id_fields = ("target_style", "target_idiom", "target_master")
    show_change_link = True


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "instrument", "skill_level", "timezone", "updated_at")
    list_filter = ("instrument", "skill_level")
    search_fields = ("user__username", "user__email", "display_name")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("user",)
    filter_horizontal = ("preferred_styles", "preferred_idioms", "preferred_masters")


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
