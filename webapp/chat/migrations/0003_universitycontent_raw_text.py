from django.db import migrations, models
from django.db.models import F


def copy_content_to_raw(apps, schema_editor):
    UniversityContent = apps.get_model("chat", "UniversityContent")
    UniversityContent.objects.update(raw_text=F("content_text"))


def noop_reverse(apps, schema_editor):
    UniversityContent = apps.get_model("chat", "UniversityContent")
    UniversityContent.objects.update(raw_text="")


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0002_rename_source_codes"),
    ]

    operations = [
        migrations.AddField(
            model_name="universitycontent",
            name="raw_text",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Searchable body copy; kept in sync with ingested plain text (e.g. academic staff content).",
            ),
        ),
        migrations.RunPython(copy_content_to_raw, noop_reverse),
    ]
