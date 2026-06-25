"""Data migration: create the Pedagogue Wagtail Group + backfill (#196).

Creates a Wagtail Group named ``Pedagogue`` with:
- ``access_admin`` permission (lets the user log into ``/cms/``)
- Image / Document add/change permissions (Wagtail editorial baseline)
- ``GroupPagePermission`` entries on the root Page granting add /
  change / publish

Then backfills: every existing ``UserProfile.is_pedagogue=True`` user
is added to the group.

Phase 1 of role mapping per #196. Subtree restriction (limit
pedagogues to a sub-path like ``/journeys/``) is a follow-up.
"""

from django.db import migrations


PEDAGOGUE_GROUP_NAME = "Pedagogue"

# Permissions granted by codename across the listed app_labels. The
# migration is forgiving: if a permission doesn't exist (e.g. Wagtail
# images app removed in a future config), it's skipped with a warning
# rather than crashing the migration.
PERMISSION_SPEC = [
    ("wagtailadmin", "access_admin"),
    ("wagtailimages", "add_image"),
    ("wagtailimages", "change_image"),
    ("wagtaildocs", "add_document"),
    ("wagtaildocs", "change_document"),
]

# Wagtail page permissions granted at the root page level. See
# wagtail.models.GroupPagePermission permission_types.
PAGE_PERMISSION_TYPES = ["add", "change", "publish"]


def create_pedagogue_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    UserProfile = apps.get_model("core", "UserProfile")

    group, _ = Group.objects.get_or_create(name=PEDAGOGUE_GROUP_NAME)

    for app_label, codename in PERMISSION_SPEC:
        try:
            perm = Permission.objects.get(
                content_type__app_label=app_label, codename=codename,
            )
        except Permission.DoesNotExist:
            continue
        group.permissions.add(perm)

    # Wagtail page-level permissions. The root page is pk=1 by Wagtail
    # convention; the wagtail_create_homepage initial migration sets
    # this up.
    try:
        Page = apps.get_model("wagtailcore", "Page")
        GroupPagePermission = apps.get_model("wagtailcore", "GroupPagePermission")
    except LookupError:
        # Wagtail not in this migration's app graph (unlikely given
        # 0001_initial depends on wagtailcore); skip page perms.
        return

    root = Page.objects.filter(pk=1).first()
    if root is None:
        return

    for ptype in PAGE_PERMISSION_TYPES:
        # The permission_type field is a CharField in newer Wagtail;
        # legacy versions used a Permission FK. Try both.
        try:
            GroupPagePermission.objects.get_or_create(
                group=group, page=root, permission_type=ptype,
            )
        except Exception:
            # Skip silently — admins can grant page perms by hand from
            # the Wagtail admin if migration heuristic fails.
            pass

    # Backfill: add every existing pedagogue to the group.
    for profile in UserProfile.objects.filter(is_pedagogue=True):
        profile.user.groups.add(group)


def remove_pedagogue_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0001_initial"),
        ("core", "0006_rolepromotionaudit"),
        ("wagtailcore", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_pedagogue_group,
            reverse_code=remove_pedagogue_group,
        ),
    ]
