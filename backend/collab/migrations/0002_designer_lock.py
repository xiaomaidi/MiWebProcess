# Generated for server-authoritative designer node locks.
# The model lives in ``collab.lock_models`` (not ``collab.models``) so this
# migration is authored explicitly instead of via makemigrations.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("collab", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DesignerLock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("node_id", models.CharField(max_length=120)),
                ("session_id", models.UUIDField()),
                ("acquired_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="designer_locks",
                        to="pages.page",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="designer_locks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "wp_designer_locks",
                "ordering": ("page_id", "node_id"),
                "indexes": [
                    models.Index(fields=["page", "expires_at"], name="wp_deslock_page_exp_idx"),
                    models.Index(fields=["expires_at"], name="wp_deslock_expires_idx"),
                    models.Index(fields=["session_id"], name="wp_deslock_session_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("page", "node_id"), name="uniq_designer_lock_page_node"),
                ],
            },
        ),
    ]
