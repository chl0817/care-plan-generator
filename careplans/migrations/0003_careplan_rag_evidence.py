from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("careplans", "0002_careplan_prompt_version")]

    operations = [
        migrations.AddField(
            model_name="careplan",
            name="patient_record",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="careplan",
            name="retrieval_query",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="careplan",
            name="retrieved_chunks",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
