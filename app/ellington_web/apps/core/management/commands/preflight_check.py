"""``manage.py preflight_check`` — readiness gate for the deploy pod.

Exits non-zero if the running code expects DB state that hasn't been
migrated yet. Wire into Kubernetes as a readiness probe so a pod with
stale schema doesn't receive traffic.

Per #213 (defensive follow-up to #171). The proper fix for unapplied
migrations is a PreSync migrate Job in the manifests repo — this
command is the application-side gate that turns silent-failure into
loud-failure.

Read-only by design: this command does NOT apply migrations.
Applying is the deployer's job (or a manual operator).

Usage::

    python manage.py preflight_check          # quiet on success
    python manage.py preflight_check --verbose

Exit codes:
    0 — all migrations applied; ready to serve
    1 — migrations pending; not ready

Designed to be cheap and side-effect-free so it's safe to call from
a readiness probe at high frequency.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = (
        "Verify the running code's expected DB schema matches what's "
        "actually applied. Exit non-zero if any migrations are pending."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print the count + names of pending migrations on "
            "failure. Quiet otherwise so probe logs aren't noisy.",
        )
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help="DB alias to check (defaults to %(default)r).",
        )

    def handle(self, *args, **options) -> None:
        verbose = options["verbose"]
        db_alias = options["database"]

        connection = connections[db_alias]
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)

        if not plan:
            if verbose:
                self.stdout.write(self.style.SUCCESS("preflight ok"))
            return

        # Pending migrations — fail loudly.
        pending = [
            f"{migration.app_label}.{migration.name}"
            for migration, _backwards in plan
        ]
        message = (
            f"preflight FAIL: {len(pending)} pending migration(s)"
        )
        if verbose:
            message += "\n  " + "\n  ".join(pending)
        # Use SystemExit so callers (probe / shell) get a non-zero
        # status even when DEBUG mishandles BaseCommand exceptions.
        self.stderr.write(self.style.ERROR(message))
        raise SystemExit(1)
