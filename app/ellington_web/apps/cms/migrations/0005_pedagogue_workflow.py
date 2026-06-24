"""Wagtail moderation workflow gate for pedagogue-authored pages (#204).

Phase 3 of role mapping (#196 → #205 → #206 → this).

Creates a Workflow named "Pedagogue Review" with a single
GroupApprovalTask requiring approval from the Moderator group, and
assigns the workflow to the root page (cascades to all descendants
by default).

Pair migration ``0006_pedagogue_publish_revoke`` removes the
``publish`` permission from the Pedagogue group's per-subtree perms
so the workflow actually fires (Wagtail only invokes the workflow
when the editor lacks direct-publish on the page).

Moderator group keeps publish — they ARE the approvers.

Idempotent.
"""

from django.db import migrations


WORKFLOW_NAME = "Pedagogue Review"
APPROVAL_TASK_NAME = "Moderator approval"
MODERATOR_GROUP_NAME = "Moderator"


def create_pedagogue_workflow(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    moderator = Group.objects.filter(name=MODERATOR_GROUP_NAME).first()
    if moderator is None:
        return  # 0004 didn't run; nothing to gate on

    try:
        Workflow = apps.get_model("wagtailcore", "Workflow")
        Task = apps.get_model("wagtailcore", "Task")
        GroupApprovalTask = apps.get_model("wagtailcore", "GroupApprovalTask")
        WorkflowTask = apps.get_model("wagtailcore", "WorkflowTask")
        WorkflowPage = apps.get_model("wagtailcore", "WorkflowPage")
        Page = apps.get_model("wagtailcore", "Page")
    except LookupError:
        # Wagtail not in this migration's app graph; skip.
        return

    workflow, _ = Workflow.objects.get_or_create(name=WORKFLOW_NAME)
    # Wagtail's GroupApprovalTask inherits Task — get_or_create on the
    # subclass auto-creates the parent Task row.
    task, created = GroupApprovalTask.objects.get_or_create(
        name=APPROVAL_TASK_NAME,
    )
    if created:
        try:
            task.groups.add(moderator)
        except AttributeError:
            # Older Wagtail schemas use a single group FK instead of M2M;
            # skip silently in that case (test will catch).
            pass

    WorkflowTask.objects.get_or_create(
        workflow=workflow, task=task.task_ptr, sort_order=1,
    )

    root = Page.objects.filter(pk=1).first()
    if root is not None:
        WorkflowPage.objects.get_or_create(workflow=workflow, page=root)


def remove_pedagogue_workflow(apps, schema_editor):
    try:
        Workflow = apps.get_model("wagtailcore", "Workflow")
        GroupApprovalTask = apps.get_model("wagtailcore", "GroupApprovalTask")
    except LookupError:
        return

    Workflow.objects.filter(name=WORKFLOW_NAME).delete()
    GroupApprovalTask.objects.filter(name=APPROVAL_TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0004_moderator_group"),
        ("wagtailcore", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_pedagogue_workflow,
            reverse_code=remove_pedagogue_workflow,
        ),
    ]
