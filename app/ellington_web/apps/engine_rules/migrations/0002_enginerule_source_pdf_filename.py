from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("engine_rules", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="enginerule",
            name="source_pdf_filename",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Filename of the source PDF the anchor was extracted"
                    " from. Populated by plugin #567 source_locator."
                    " Surfaced in the rule_review UI as 'Page N of"
                    " <filename>'. Empty when the source isn't a tracked"
                    " PDF (e.g. transcript-only rules)."
                ),
                max_length=255,
            ),
        ),
    ]
