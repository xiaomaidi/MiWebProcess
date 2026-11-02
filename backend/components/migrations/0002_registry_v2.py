from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="componentmeta",
            name="actions_supported",
            field=models.JSONField(blank=True, default=list, verbose_name="支持动作"),
        ),
        migrations.AddField(
            model_name="componentmeta",
            name="default_children",
            field=models.JSONField(blank=True, default=list, verbose_name="默认子节点"),
        ),
        migrations.AddField(
            model_name="componentmeta",
            name="element",
            field=models.CharField(blank=True, default="", max_length=128, verbose_name="渲染元素"),
        ),
        migrations.AddField(
            model_name="componentmeta",
            name="is_container",
            field=models.BooleanField(default=False, verbose_name="容器组件"),
        ),
        migrations.AddField(
            model_name="componentmeta",
            name="is_form_field",
            field=models.BooleanField(default=False, verbose_name="表单字段"),
        ),
        migrations.AddField(
            model_name="componentmeta",
            name="source",
            field=models.CharField(blank=True, default="element-plus", max_length=32, verbose_name="实现来源"),
        ),
        migrations.AddField(
            model_name="componentmeta",
            name="style_schema",
            field=models.JSONField(blank=True, default=dict, verbose_name="样式 Schema"),
        ),
        migrations.AlterField(
            model_name="componentmeta",
            name="type",
            field=models.CharField(
                choices=[
                    ("basic", "basic"),
                    ("layout", "layout"),
                    ("form", "form"),
                    ("chart", "chart"),
                    ("business", "business"),
                    ("data", "data"),
                    ("feedback", "feedback"),
                    ("nav", "nav"),
                    ("media", "media"),
                    ("advanced", "advanced"),
                    ("custom", "custom"),
                ],
                default="basic",
                max_length=16,
                verbose_name="类型",
            ),
        ),
    ]
