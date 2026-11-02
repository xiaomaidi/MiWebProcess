from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AiProvider",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("provider_type", models.CharField(choices=[("deepseek", "DeepSeek"), ("openai", "OpenAI"), ("ollama", "Ollama"), ("custom", "OpenAI-compatible")], default="deepseek", max_length=20)),
                ("base_url", models.CharField(max_length=500)),
                ("model", models.CharField(default="deepseek-chat", max_length=160)),
                ("api_key", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("temperature", models.FloatField(default=0.4)),
                ("timeout", models.IntegerField(default=90)),
                ("last_test_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "wp_ai_providers",
                "ordering": ("-is_default", "id"),
            },
        ),
    ]
