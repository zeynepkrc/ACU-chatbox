from django.db import models


class UniversityContent(models.Model):
    """Public web content ingested for the chatbot (one row per canonical source URL)."""

    class Source(models.TextChoices):
        ACIBADEM_MAIN = "acibadem_main", "Acıbadem main site"
        BOLOGNA_OBS = "bologna_obs", "OBS Bologna (public)"

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
    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["source", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} — {self.title or self.source_url[:80]}"
