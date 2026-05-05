from django.db import models


class UniversityContent(models.Model):
    """Public web content ingested for the chatbot (one row per canonical source URL)."""

    class Source(models.TextChoices):
        MAIN = "main", "Acıbadem main website"
        BOLOGNA = "bologna", "OBS / Bologna (public)"

    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        db_index=True,
    )
    source_url = models.URLField(
        max_length=2048,
        unique=True,
        help_text="Canonical public URL; duplicates are rejected at the database level.",
    )
    title = models.CharField(max_length=512, blank=True, default="")
    content_text = models.TextField(
        help_text="Plain text with HTML removed and normalized whitespace.",
    )
    raw_text = models.TextField(
        blank=True,
        default="",
        help_text="Searchable body copy; kept in sync with ingested plain text (e.g. academic staff content).",
    )
    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["source", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} — {self.title or self.source_url[:80]}"
