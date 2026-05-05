from django.contrib import admin
from django.utils.html import format_html

from .models import UniversityContent


@admin.register(UniversityContent)
class UniversityContentAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "title",
        "link",
        "scraped_at",
        "updated_at",
    )
    list_filter = ("source",)
    search_fields = ("title", "source_url", "content_text", "raw_text")
    readonly_fields = ("scraped_at", "updated_at")
    ordering = ("-updated_at",)

    @admin.display(description="URL")
    def link(self, obj: UniversityContent) -> str:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            obj.source_url,
            obj.source_url[:72] + ("…" if len(obj.source_url) > 72 else ""),
        )
