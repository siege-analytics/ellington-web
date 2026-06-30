# Hand-written: parallels prior cms / voicings hand-writes per
# the same GDAL-unavailable-locally pattern (#233 / epic #232).
# CI runs `makemigrations --check` to confirm parity.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SoundBank",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_app", models.CharField(choices=[("musescore", "MuseScore"), ("user", "User"), ("system", "System"), ("other", "Other")], db_index=True, help_text="Which install the bank came from. Drives display grouping in the picker UI.", max_length=16)),
                ("name", models.CharField(help_text="Display name. Defaults to file basename; operator can override via admin.", max_length=255)),
                ("format", models.CharField(choices=[("sf2", "SF2"), ("sf3", "SF3"), ("dls", "DLS")], db_index=True, max_length=8)),
                ("path", models.CharField(help_text="Absolute path on the machine where ``scan_sound_banks`` ran. Stored verbatim for audit; NOT the identity field.", max_length=1024)),
                ("size_bytes", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(help_text="Identity key. Re-scanning the same file is a no-op.", max_length=64, unique=True)),
                ("is_active", models.BooleanField(db_index=True, default=True, help_text="False to hide from the picker without deleting.")),
                ("scanned_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["source_app", "name"],
            },
        ),
        migrations.AddIndex(
            model_name="soundbank",
            index=models.Index(fields=["source_app", "is_active"], name="soundbank_app_active_idx"),
        ),
    ]
