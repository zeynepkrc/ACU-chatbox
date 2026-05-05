from __future__ import annotations

from django.core.management.base import BaseCommand

from chat.models import UniversityContent
from scraper.acibadem_main import run as run_main
from scraper.bologna import run as run_bologna


class Command(BaseCommand):
    help = "Ana site ve Bologna scraper’larını sırayla çalıştırır (manuel Z7)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            default=False,
            help="Her iki scraper için reset=True (ilgili source kayıtları silinir).",
        )
        parser.add_argument(
            "--main-pages",
            type=int,
            default=80,
            metavar="N",
            help="acibadem_main.run(max_pages=N) (varsayılan: 80).",
        )
        parser.add_argument(
            "--bologna-pages",
            type=int,
            default=40,
            metavar="N",
            help="bologna.run(max_pages=N) (varsayılan: 40).",
        )

    def handle(self, *args, **options) -> None:
        reset: bool = bool(options["reset"])
        main_pages: int = int(options["main_pages"])
        bologna_pages: int = int(options["bologna_pages"])

        self.stdout.write("Running main scraper...")
        self.stdout.flush()
        main_result = run_main(max_pages=main_pages, reset=reset)
        self.stdout.write(f"{main_result}")
        self.stdout.flush()

        self.stdout.write("Running bologna scraper...")
        self.stdout.flush()
        bologna_result = run_bologna(max_pages=bologna_pages, reset=reset)
        self.stdout.write(f"{bologna_result}")
        self.stdout.flush()

        total = UniversityContent.objects.count()
        self.stdout.write(f"Total records: {total}")
        self.stdout.flush()
