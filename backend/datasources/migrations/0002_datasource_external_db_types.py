from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("datasources", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datasource",
            name="type",
            field=models.CharField(
                choices=[
                    ("rest", "REST"),
                    ("sql", "系统内置 SQL"),
                    ("mysql", "MySQL"),
                    ("postgres", "PostgreSQL"),
                    ("sqlserver", "SQL Server"),
                    ("static", "静态"),
                ],
                max_length=20,
            ),
        ),
    ]
