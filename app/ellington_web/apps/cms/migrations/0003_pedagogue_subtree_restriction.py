"""Restrict the Pedagogue Wagtail group to editorial subtrees (#205).

Phase 2 of role mapping (#196). The Phase 1 migration
(0002_pedagogue_group) granted ``add`` / ``change`` / ``publish`` on
the root page, which is too broad once a real content tree exists:
a pedagogue could accidentally edit ``/about/`` or marketing copy.

This migration:
1. Removes any existing root-level ``GroupPagePermission`` rows for
   the Pedagogue group.
2. For each slug in ``settings.PEDAGOGUE_AUTHORABLE_PAGE_SLUGS``,
   grants ``add`` / ``change`` / ``publish`` on the page at that
   slug under root — IF the page exists.
3. Configured slugs without a matching page are skipped silently;
   when the subtree later lands, rerun ``manage.py migrate cms``.

Pedagogues retain ``access_admin`` regardless, so they can still log
into /cms/ even if no editorial subtree exists yet (fresh DB with
only the spike HomePage).

Idempotent: re-running yields the same permission rows.
"""

from django.conf import settings
from django.db import migrations


PEDAGOGUE_GROUP_NAME = "Pedagogue"
PAGE_PERMISSION_TYPES = ["add", "change", "publish"]


def restrict_to_subtrees(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    try:
        Page = apps.get_model("wagtailcore", "Page")
        GroupPagePermission = apps.get_model("wagtailcore", "GroupPagePermission")
    except LookupError:
        return

    group = Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).first()
    if group is None:
        return

    root = Page.objects.filter(pk=1).first()
    if root is not None:
        GroupPagePermission.objects.filter(group=group, page=root).delete()

    slugs = getattr(settings, "PEDAGOGUE_AUTHORABLE_PAGE_SLUGS", [])
    for slug in slugs:
        page = Page.objects.filter(slug=slug, depth=2).first()
        if page is None:
            continue
        for ptype in PAGE_PERMISSION_TYPES:
            try:
                GroupPagePermission.objects.get_or_create(
                    group=group, page=page, permission_type=ptype,
                )
            except Exception:
                # Schema-version mismatch on permission_type field.
                # Admins can grant manually from the Wagtail admin if
                # the heuristic doesn't apply.
                pass


def restore_root_permission(apps, schema_editor):
    """Reverse: restore root-level perm so demoting this PR doesn't
    leave pedagogues stranded."""
    Group = apps.get_model("auth", "Group")
    try:
        Page = apps.get_model("wagtailcore", "Page")
        GroupPagePermission = apps.get_model("wagtailcore", "GroupPagePermission")
    except LookupError:
        return

    group = Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).first()
    if group is None:
        return
    root = Page.objects.filter(pk=1).first()
    if root is None:
        return

    slugs = getattr(settings, "PEDAGOGUE_AUTHORABLE_PAGE_SLUGS", [])
    for slug in slugs:
        page = Page.objects.filter(slug=slug, depth=2).first()
        if page is None:
            continue
        GroupPagePermission.objects.filter(group=group, page=page).delete()

    for ptype in PAGE_PERMISSION_TYPES:
        try:
            GroupPagePermission.objects.get_or_create(
                group=group, page=root, permission_type=ptype,
            )
        except Exception:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0002_pedagogue_group"),
        ("wagtailcore", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            restrict_to_subtrees,
            reverse_code=restore_root_permission,
        ),
    ]
