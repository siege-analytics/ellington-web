# Hand-written: GDAL/GeoDjango not always available locally so
# `makemigrations` is skipped here; CI runs `--check` to confirm parity
# (mirror of the rule_review 0003 pattern). Refs #186 Phase 2.

import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='VoicingBundle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plugin_commit_sha', models.CharField(help_text='Plugin git SHA the voicings.json was fetched from. Synthesized at sync time since voicings.json has no top-level manifest block (engine_rules.json does — contract gap to close upstream).', max_length=40)),
                ('source_url', models.CharField(help_text='URL the voicings.json was fetched from (raw GitHub or release asset). Stored verbatim for audit.', max_length=512)),
                ('built_at', models.DateTimeField(help_text='File mtime in the plugin repo at fetch time, OR explicit override via --built-at on sync. Mirrors ``EngineRulesBundle.built_at``.')),
                ('total_voicings', models.PositiveIntegerField(help_text='Sanity check — the importer asserts this matches the number of rows ingested before committing.')),
                ('raw_top_level', models.JSONField(help_text='The voicings.json top-level dict minus the ``voicings`` array. Empty today; future-proof for when the plugin adds a manifest block.')),
                ('is_active', models.BooleanField(default=False, help_text='True for the bundle whose Voicing rows are surfaced in browse views. Only one bundle is active at a time. sync_voicings deactivates prior actives on success.')),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-imported_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='voicingbundle',
            constraint=models.UniqueConstraint(fields=('plugin_commit_sha',), name='voicingbundle_sha_unique'),
        ),
        migrations.CreateModel(
            name='Voicing',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('voicing_id', models.CharField(help_text='Plugin\'s ``id`` field (e.g. ``c13b9-cm6-altered-6str-26``). Unique within a bundle.', max_length=128)),
                ('name', models.CharField(help_text='Human-readable name (e.g. ``C7 — Shell 137 — E str``).', max_length=256)),
                ('chord_quality', models.CharField(db_index=True, help_text='Free-text chord quality token. Most rules bind to ``maj7`` / ``dom7`` / ``min7`` etc., but the plugin schema allows any string (e.g. ``dom7b9``).', max_length=64)),
                ('root', models.CharField(db_index=True, help_text='Plugin stores everything at ``C``. Indexed for the day transpose-on-store lands (not Phase 2).', max_length=2)),
                ('category', models.CharField(db_index=True, help_text='Voicing category (e.g. ``shell``, ``drop2``, ``drop3``, ``extended``, ``altered``, ``quartal``).', max_length=64)),
                ('suitable_modes', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=32), blank=True, default=list, help_text='``chord-melody`` / ``comping`` / ``solo-guitar`` / ``duo``. Soft hint per plugin schema, not a hard filter.', size=None)),
                ('strings', models.PositiveSmallIntegerField(help_text='Instrument string count (6 = standard, 7 = Van Eps).')),
                ('tuning', models.CharField(blank=True, default='', help_text='Tuning config name (matches plugin ``config/tunings/``). Empty = standard.', max_length=64)),
                ('fret_number', models.PositiveSmallIntegerField(help_text='Starting fret for the diagram (row 1).')),
                ('visible_frets', models.PositiveSmallIntegerField(help_text='Number of frets shown in the diagram.')),
                ('dots', models.JSONField(help_text='List of ``{string, fret}`` dicts — fingered positions. Stored as JSON since each entry is a small object.')),
                ('mutes', django.contrib.postgres.fields.ArrayField(base_field=models.PositiveSmallIntegerField(), blank=True, default=list, help_text='String numbers muted (X above the nut).', size=None)),
                ('open_strings', django.contrib.postgres.fields.ArrayField(base_field=models.PositiveSmallIntegerField(), blank=True, default=list, help_text='String numbers played open (O above the nut). Named ``open_strings`` to avoid Python\'s builtin ``open``.', size=None)),
                ('notes', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=4), blank=True, default=list, help_text="Note names sounding, low-to-high (e.g. ``['C', 'E', 'Bb', 'Db', 'E', 'A']``).", size=None)),
                ('intervals', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=8), blank=True, default=list, help_text="Intervals above root for each sounding note (e.g. ``['1', '3', 'b7', 'b9']``).", size=None)),
                ('tags', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=64), blank=True, default=list, help_text='Free-text labels (e.g. ``calculated``, ``laukens-coverage``).', size=None)),
                ('also_qualities', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=64), blank=True, default=list, help_text="Additional chord_quality tokens this voicing satisfies (the plugin's ranker uses this for substitution).", size=None)),
                ('shape_id', models.CharField(blank=True, default='', help_text="Plugin's geometric-shape dedup hash. Empty when the plugin didn't emit one.", max_length=32)),
                ('is_active', models.BooleanField(db_index=True, default=True, help_text='Mirrors bundle.is_active at ingest time. Browse views filter on this.')),
                ('bundle', models.ForeignKey(help_text='Source bundle. PROTECT so deleting a bundle out from under future cross-references (Phase 2b/3 will FK from PedagogueConfirmation) doesn\'t orphan rows.', on_delete=django.db.models.deletion.PROTECT, related_name='voicings', to='voicings.voicingbundle')),
            ],
            options={
                'ordering': ['chord_quality', 'category', 'voicing_id'],
            },
        ),
        migrations.AddConstraint(
            model_name='voicing',
            constraint=models.UniqueConstraint(fields=('bundle', 'voicing_id'), name='voicing_bundle_id_unique'),
        ),
        migrations.AddIndex(
            model_name='voicing',
            index=models.Index(fields=['chord_quality', 'category'], name='voicing_quality_cat_idx'),
        ),
        migrations.AddIndex(
            model_name='voicing',
            index=models.Index(fields=['is_active', 'chord_quality'], name='voicing_active_quality_idx'),
        ),
    ]
