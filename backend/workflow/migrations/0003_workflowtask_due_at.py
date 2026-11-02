from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0002_rename_wp_workflow_app_id_5f0c2e_idx_wp_workflow_app_id_ac4461_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtask",
            name="due_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
