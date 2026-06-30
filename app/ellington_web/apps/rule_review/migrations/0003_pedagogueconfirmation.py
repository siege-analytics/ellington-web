# Hand-written: GDAL/GeoDjango unavailable locally so makemigrations
# is skipped here; CI runs --check to confirm parity (#186 Phase 1).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('engine_rules', '0001_initial'),
        ('rule_review', '0002_alter_response_user'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PedagogueConfirmation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('voicing_confirmed', models.BooleanField(default=False, help_text="Is the rule's then_action voicing recommendation correct for its quality_binding context?")),
                ('voicing_note', models.TextField(blank=True, help_text='Optional disagreement / clarification on the voicing axis. Empty when voicing_confirmed = True with no caveats.')),
                ('naming_confirmed', models.BooleanField(default=False, help_text="Is the rule's quality_binding canonical token correctly classifying the chord context the rule is about?")),
                ('naming_note', models.TextField(blank=True)),
                ('lesson_confirmed', models.BooleanField(default=False, help_text='Does the anchor quote faithfully support the rule and is the falsifier pedagogically sound?')),
                ('lesson_note', models.TextField(blank=True)),
                ('overall_confidence', models.SmallIntegerField(blank=True, null=True, help_text='1-5 Likert: how sound is this rule as a complete pedagogical unit? Null = no opinion expressed.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('rule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='confirmations', to='engine_rules.enginerule')),
                ('user', models.ForeignKey(help_text='The pedagogue who confirmed. PROTECT — sentinel-anonymize on user delete to preserve corpus signal.', on_delete=django.db.models.deletion.PROTECT, related_name='rule_confirmations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='pedagogueconfirmation',
            constraint=models.UniqueConstraint(fields=('rule', 'user'), name='pedagogueconfirmation_rule_user_unique'),
        ),
        migrations.AddConstraint(
            model_name='pedagogueconfirmation',
            constraint=models.CheckConstraint(
                condition=models.Q(('overall_confidence__isnull', True)) | models.Q(('overall_confidence__range', (1, 5))),
                name='pedagogueconfirmation_confidence_range',
            ),
        ),
        migrations.AddIndex(
            model_name='pedagogueconfirmation',
            index=models.Index(fields=['rule', 'voicing_confirmed', 'naming_confirmed', 'lesson_confirmed'], name='pedconf_rule_axes_idx'),
        ),
        migrations.AddIndex(
            model_name='pedagogueconfirmation',
            index=models.Index(fields=['user', '-updated_at'], name='pedconf_user_recent_idx'),
        ),
    ]
