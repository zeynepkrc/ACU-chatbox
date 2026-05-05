# Merge branch: 0003_add_chat_history (ChatHistory) vs 0003_universitycontent_raw_text (raw_text).
# No schema operations — both parents are already compatible leaves from 0002.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0003_add_chat_history"),
        ("chat", "0003_universitycontent_raw_text"),
    ]

    operations = []
