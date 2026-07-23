from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("careplans", "0003_careplan_rag_evidence")]

    operations = [
        migrations.AddField(
            model_name="careplan",
            name="structured_data",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="careplan",
            name="parse_failed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="careplan",
            name="raw_output",
            field=models.TextField(blank=True, default=""),
        ),
    ]
