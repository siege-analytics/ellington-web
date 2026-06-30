"""Revoke ``publish`` from the Pedagogue group's per-subtree perms (#204).

Pair migration with ``0005_pedagogue_workflow``. Without this, the
workflow created in 0005 never fires — Wagtail only routes
submissions through workflow if the editor lacks direct-publish on
the target page.

After this migration, pedagogues keep ``add`` and ``change`` on
configured editorial subtrees (per #205) but lose ``publish``.
Clicking "Publish" on their pages opens "Submit for moderation"
instead. Moderators (#206) approve from the Wagtail "Moderation"
view; on approval, Wagtail publishes the page.

Reverse migration restores ``publish`` so a workflow rollback
doesn't leave pedagogues unable to push live.
"""

from django.conf import settings
from django.db import migrations


PEDAGOGUE_GROUP_NAME = "Pedagogue"
REVOKED_PERMISSION_TYPE = "publish"


def revoke_pedagogue_publish(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    try:
        Page = apps.get_model("wagtailcore", "Page")
        GroupPagePermission = apps.get_model(
            "wagtailcore", "GroupPagePermission",
        )
    except LookupError:
        return

    group = Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).first()
    if group is None:
        return

    slugs = getattr(settings, "PEDAGOGUE_AUTHORABLE_PAGE_SLUGS", [])
    for slug in slugs:
        page = Page.objects.filter(slug=slug, depth=2).first()
        if page is None:
            continue
        GroupPagePermission.objects.filter(
            group=group, page=page, permission_type=REVOKED_PERMISSION_TYPE,
        ).delete()


def restore_pedagogue_publish(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    try:
        Page = apps.get_model("wagtailcore", "Page")
        GroupPagePermission = apps.get_model(
            "wagtailcore", "GroupPagePermission",
        )
    except LookupError:
        return

    group = Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).first()
    if group is None:
        return

    slugs = getattr(settings, "PEDAGOGUE_AUTHORABLE_PAGE_SLUGS", [])
    for slug in slugs:
        page = Page.objects.filter(slug=slug, depth=2).first()
        if page is None:
            continue
        try:
            GroupPagePermission.objects.get_or_create(
                group=group, page=page,
                permission_type=REVOKED_PERMISSION_TYPE,
            )
        except Exception:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0005_pedagogue_workflow"),
    ]

    operations = [
        migrations.RunPython(
            revoke_pedagogue_publish,
            reverse_code=restore_pedagogue_publish,
        ),
    ]
