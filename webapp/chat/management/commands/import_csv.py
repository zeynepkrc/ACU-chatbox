import csv
from django.core.management.base import BaseCommand
from chat.models import PageContent


class Command(BaseCommand):
    help = "Import scraped CSV data into PageContent"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **kwargs):
        csv_path = kwargs["csv_path"]

        with open(csv_path, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file, delimiter="|")

            for row in reader:
                # kolon isimlerini temizle
                clean_row = {k.strip().replace('"', ''): v for k, v in row.items()}

                PageContent.objects.update_or_create(
                    url=clean_row["url"],
                    defaults={
                        "title": f"{clean_row.get('main_section', '')} - {clean_row.get('sub_section', '')}".strip(" -"),
                        "content": clean_row.get("content", ""),
                        "source": "scraper",
                    }
                )

        self.stdout.write(self.style.SUCCESS("CSV data imported successfully."))