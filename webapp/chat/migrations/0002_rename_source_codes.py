from django.db import migrations


def forwards(apps, schema_editor):
    UniversityContent = apps.get_model("chat", "UniversityContent")
    UniversityContent.objects.filter(source="acibadem_main").update(source="main")
    UniversityContent.objects.filter(source="bologna_obs").update(source="bologna")


def backwards(apps, schema_editor):
    UniversityContent = apps.get_model("chat", "UniversityContent")
    UniversityContent.objects.filter(source="main").update(source="acibadem_main")
    UniversityContent.objects.filter(source="bologna").update(source="bologna_obs")


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
