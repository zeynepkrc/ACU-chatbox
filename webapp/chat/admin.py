from django.contrib import admin
from django.utils.html import format_html

from .models import ChatHistory, UniversityContent


@admin.register(UniversityContent)
class UniversityContentAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "title",
        "link",
        "scraped_at",
        "updated_at",
    )
    list_filter = (
        "source",
        ("scraped_at", admin.DateFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    search_fields = ("title", "source_url", "content_text")
    readonly_fields = ("scraped_at", "updated_at")
    ordering = ("-updated_at",)

    @admin.display(description="URL")
    def link(self, obj: UniversityContent) -> str:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            obj.source_url,
            obj.source_url[:72] + ("…" if len(obj.source_url) > 72 else ""),
        )


@admin.register(ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user_query_preview",
        "ai_response_preview",
    )
    list_filter = (("created_at", admin.DateFieldListFilter),)
    search_fields = ("user_query", "ai_response")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    @admin.display(description="User query")
    def user_query_preview(self, obj: ChatHistory) -> str:
        text = (obj.user_query or "").strip()
        if len(text) <= 100:
            return text
        return text[:100] + "…"

    @admin.display(description="AI response")
    def ai_response_preview(self, obj: ChatHistory) -> str:
        text = (obj.ai_response or "").strip()
        if len(text) <= 100:
            return text
        return text[:100] + "…"
