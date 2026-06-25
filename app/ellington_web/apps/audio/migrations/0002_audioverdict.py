# Hand-written: GDAL unavailable locally. Parallels prior cms /
# voicings / audio hand-writes. Per #250 / epic #232.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audio", "0001_initial"),
        ("practice", "0008_alter_invite_email_alter_invite_expires_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AudioVerdict",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slice_id", models.CharField(db_index=True, help_text="Slice ID from slicer.slices_for_song. Together with rule_id forms the unique key.", max_length=64)),
                ("rule_id", models.CharField(db_index=True, help_text="EngineRule.rule_id this verdict applies to. Not a FK because EngineRule rows can be deactivated; we want the verdict to survive corpus rotation.", max_length=128)),
                ("rule_polarity", models.CharField(choices=[("positive", "Positive (prescribe)"), ("avoid", "Avoid")], help_text="Mirrors RuleFireResult.polarity at the time the verdict was computed.", max_length=16)),
                ("verdict", models.CharField(choices=[("satisfies", "Satisfies"), ("violates", "Violates"), ("neutral", "Neutral (deferred)"), ("indeterminate", "Indeterminate (low confidence)")], db_index=True, max_length=16)),
                ("evidence_type", models.CharField(db_index=True, help_text="Discriminator from the EvidenceUnion variant (chord_tone_membership / scale_drift / deferred / voicing_match / rhythm_attack).", max_length=32)),
                ("evidence_payload", models.JSONField(default=dict, help_text="The evidence variant's fields, serialized via dataclasses.asdict. Schema is the §10.5 union; the UI renders per evidence_type.")),
                ("verdict_confidence", models.FloatField(db_index=True, default=0.0, help_text="§10.6 composite = observation_confidence × rule_evaluability_confidence.")),
                ("rule_evaluability_confidence", models.FloatField(default=0.0, help_text="§10.6 rule-shape complexity component, separable from observation_confidence for debug.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recording", models.ForeignKey(help_text="The Recording this verdict was computed from.", on_delete=django.db.models.deletion.CASCADE, related_name="audio_verdicts", to="practice.recording")),
            ],
            options={
                "ordering": ["recording", "slice_id", "rule_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="audioverdict",
            constraint=models.UniqueConstraint(fields=("recording", "slice_id", "rule_id"), name="audioverdict_recording_slice_rule_unique"),
        ),
        migrations.AddIndex(
            model_name="audioverdict",
            index=models.Index(fields=["recording", "verdict"], name="audioverdict_rec_verdict_idx"),
        ),
    ]
