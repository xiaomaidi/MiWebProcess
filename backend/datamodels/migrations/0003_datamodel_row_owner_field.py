from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("datamodels", "0002_datamodel_is_public"),
    ]

    operations = [
        migrations.AddField(
            model_name="datamodel",
            name="row_owner_field",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
    ]
