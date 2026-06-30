"""Create the Moderator Wagtail Group + backfill (#206).

Mirror of 0002_pedagogue_group's shape but for admins
(``User.is_staff``). Moderator group gets root-level page perms
intentionally (moderators see everything across the tree).

Closes the gap from #196 Phase 1: today, a staff user who isn't
also a superuser can't moderate Wagtail content. After this
migration, ``is_staff`` is sufficient.

Idempotent.
"""

from django.db import migrations


MODERATOR_GROUP_NAME = "Moderator"

PERMISSION_SPEC = [
    ("wagtailadmin", "access_admin"),
    ("wagtailimages", "add_image"),
    ("wagtailimages", "change_image"),
    ("wagtailimages", "delete_image"),
    ("wagtaildocs", "add_document"),
    ("wagtaildocs", "change_document"),
    ("wagtaildocs", "delete_document"),
]
PAGE_PERMISSION_TYPES = ["add", "change", "publish"]


def create_moderator_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")

    group, _ = Group.objects.get_or_create(name=MODERATOR_GROUP_NAME)

    for app_label, codename in PERMISSION_SPEC:
        try:
            perm = Permission.objects.get(
                content_type__app_label=app_label, codename=codename,
            )
        except Permission.DoesNotExist:
            continue
        group.permissions.add(perm)

    try:
        Page = apps.get_model("wagtailcore", "Page")
        GroupPagePermission = apps.get_model(
            "wagtailcore", "GroupPagePermission",
        )
    except LookupError:
        return

    root = Page.objects.filter(pk=1).first()
    if root is not None:
        for ptype in PAGE_PERMISSION_TYPES:
            try:
                GroupPagePermission.objects.get_or_create(
                    group=group, page=root, permission_type=ptype,
                )
            except Exception:
                pass

    # Backfill: every existing is_staff user added to the Moderator group.
    for user in User.objects.filter(is_staff=True):
        user.groups.add(group)


def remove_moderator_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=MODERATOR_GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0003_pedagogue_subtree_restriction"),
        ("wagtailcore", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_moderator_group,
            reverse_code=remove_moderator_group,
        ),
    ]
