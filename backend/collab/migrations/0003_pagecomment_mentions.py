# Generated for PageComment.mentions (@ 提及).
# 0002 由服务端节点锁功能占用，故本迁移显式排在它之后。
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("collab", "0002_designer_lock"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagecomment",
            name="mentions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
