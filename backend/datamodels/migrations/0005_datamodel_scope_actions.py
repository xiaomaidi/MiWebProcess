from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("datamodels", "0003_datamodel_row_owner_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="datamodel",
            name="data_scope",
            field=models.CharField(default="all", max_length=20),
        ),
        migrations.AddField(
            model_name="datamodel",
            name="action_roles",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
