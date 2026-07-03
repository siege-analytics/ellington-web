"""Merge migration for cms — reconciles two leaf nodes on develop.

The cms migration graph split when #282 (MasterProfilePage / seed
Joe Pass) and #283 → #285 (subtree restriction → moderator group →
workflow → publish revoke) landed with overlapping numeric prefixes
without a common downstream parent.

Chain A: 0002_pedagogue_group → 0003_masters_index_and_profile → 0004_seed_joe_pass (leaf)
Chain B: 0002_pedagogue_group → 0003_pedagogue_subtree_restriction → 0004_moderator_group → 0005_pedagogue_workflow → 0006_pedagogue_publish_revoke (leaf)

This migration is a no-op that depends on both leaves so the graph
has a single downstream head again. Django's ``makemigrations
--merge`` would generate the equivalent; hand-written here so
future work has a stable parent.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0004_seed_joe_pass"),
        ("cms", "0006_pedagogue_publish_revoke"),
    ]

    operations = []
