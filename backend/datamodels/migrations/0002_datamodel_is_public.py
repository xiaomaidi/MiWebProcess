from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("datamodels", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="datamodel",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
    ]
