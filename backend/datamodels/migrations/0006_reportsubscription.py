from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("appcore", "0001_initial"),
        ("datamodels", "0005_datamodel_scope_actions"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("frequency", models.CharField(choices=[("daily", "每日"), ("weekly", "每周"), ("monthly", "每月")], default="weekly", max_length=20)),
                ("recipients", models.CharField(blank=True, default="", max_length=500)),
                ("enabled", models.BooleanField(default=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_subscriptions", to="appcore.app")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("model", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_subscriptions", to="datamodels.datamodel")),
            ],
            options={
                "db_table": "wp_report_subscriptions",
                "unique_together": {("app", "name")},
            },
        ),
    ]
