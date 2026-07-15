from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("careplans", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="careplan",
            name="prompt_version",
            field=models.CharField(default="v1", max_length=50),
        ),
    ]
