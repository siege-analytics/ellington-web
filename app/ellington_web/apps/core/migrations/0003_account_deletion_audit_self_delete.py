"""Make AccountDeletionAudit.deleted_by nullable + SET_NULL to support
self-delete; add denormalized initiated_by_username text snapshot.

Per epic #96 sub-ticket (k) / #112. The self-service /accounts/delete/
view passes ``initiated_by=request.user``; when the user IS the target,
PROTECT on the FK would block User.delete(). Switching to SET_NULL +
text snapshot keeps the audit row truthful without the protect-block.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_pedagogue_role_and_deletion_audit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="accountdeletionaudit",
            name="initiated_by_username",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Denormalized snapshot of who initiated the deletion."
                    " For self-delete this equals deleted_username; for"
                    " admin-initiated it's the admin's username."
                ),
                max_length=150,
            ),
        ),
        migrations.AlterField(
            model_name="accountdeletionaudit",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text=(
                    "Admin who initiated the deletion. Null when the"
                    " user deleted themselves (the FK would point at"
                    " the now-gone row); see initiated_by_username for"
                    " the text snapshot."
                ),
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="account_deletions_initiated",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
