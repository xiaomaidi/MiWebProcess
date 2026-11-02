from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0003_workflowtask_due_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtask",
            name="remind_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workflowtask",
            name="last_reminded_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
