from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("appcore", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("code", models.CharField(max_length=80)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("nodes", models.JSONField(blank=True, default=list)),
                ("status", models.CharField(choices=[("draft", "草稿"), ("published", "已发布"), ("archived", "已归档")], default="draft", max_length=20)),
                ("version", models.IntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workflows", to="appcore.app")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "wp_workflow_definitions", "ordering": ("-updated_at",), "unique_together": {("app", "code")}},
        ),
        migrations.CreateModel(
            name="WorkflowInstance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("business_model_id", models.IntegerField(blank=True, null=True)),
                ("business_record_id", models.IntegerField(blank=True, null=True)),
                ("title", models.CharField(blank=True, default="", max_length=300)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("running", "审批中"), ("approved", "已通过"), ("rejected", "已驳回"), ("cancelled", "已撤回")], default="running", max_length=20)),
                ("current_node_id", models.CharField(blank=True, default="", max_length=80)),
                ("current_index", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workflow_instances", to="appcore.app")),
                ("definition", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="instances", to="workflow.workflowdefinition")),
                ("initiator", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "wp_workflow_instances", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="WorkflowTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("node_id", models.CharField(max_length=80)),
                ("node_name", models.CharField(blank=True, default="", max_length=120)),
                ("assignee_role", models.CharField(blank=True, default="", max_length=20)),
                ("status", models.CharField(choices=[("pending", "待处理"), ("approved", "已同意"), ("rejected", "已驳回"), ("transferred", "已转办"), ("cancelled", "已取消")], default="pending", max_length=20)),
                ("comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("instance", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tasks", to="workflow.workflowinstance")),
            ],
            options={"db_table": "wp_workflow_tasks", "ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="workflowinstance",
            index=models.Index(fields=["app", "status"], name="wp_workflow_app_id_5f0c2e_idx"),
        ),
        migrations.AddIndex(
            model_name="workflowtask",
            index=models.Index(fields=["assignee", "status"], name="wp_workflow_assigne_3c4d0e_idx"),
        ),
        migrations.AddIndex(
            model_name="workflowtask",
            index=models.Index(fields=["instance", "status"], name="wp_workflow_instanc_9b2a1e_idx"),
        ),
    ]
