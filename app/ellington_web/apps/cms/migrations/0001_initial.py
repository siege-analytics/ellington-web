# Hand-written: prefer real makemigrations once Wagtail is installable
# locally. CI will run `makemigrations --check` to confirm parity.
# Refs #191 spike. Depends on wagtailcore.0001_initial (creates the
# Page tree).

import django.db.models.deletion
import wagtail.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('wagtailcore', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomePage',
            fields=[
                ('page_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='wagtailcore.page')),
                ('intro', wagtail.fields.RichTextField(blank=True, help_text='Brief site introduction. Rendered on the home page.')),
            ],
            options={
                'verbose_name': 'Home page',
            },
            bases=('wagtailcore.page',),
        ),
    ]
