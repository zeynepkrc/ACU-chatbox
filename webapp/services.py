"""Retrieval helpers for RAG-style context (independent of scraper code)."""

from __future__ import annotations

import logging

from django.db.models import Case, IntegerField, Q, QuerySet, When

from chat.models import UniversityContent

logger = logging.getLogger(__name__)


def retrieve_relevant_university_content(
    query: str,
    *,
    limit: int = 5,
) -> QuerySet[UniversityContent]:
    """
    Return rows from ``UniversityContent`` most likely useful as LLM context.

    Uses case-insensitive substring match on ``title``, ``content_text``, and
    ``raw_text``. Veri silinmez; sorgu hata verirse boş queryset döner.
    """
    try:
        text = (query or "").strip()
        if not text:
            return UniversityContent.objects.none()

        words = [w for w in text.split() if len(w) >= 2]
        if not words:
            words = [text]

        combined = Q()
        for w in words:
            combined |= (
                Q(title__icontains=w)
                | Q(content_text__icontains=w)
                | Q(raw_text__icontains=w)
            )

        return (
            UniversityContent.objects.filter(combined)
            .distinct()
            .annotate(
                _title_full_match=Case(
                    When(Q(title__icontains=text), then=0),
                    default=1,
                    output_field=IntegerField(),
                ),
            )
            .order_by("_title_full_match", "-updated_at")[:limit]
        )
    except Exception:
        logger.exception("retrieve_relevant_university_content failed")
        return UniversityContent.objects.none()


def build_context_bundle_for_ai(query: str, *, limit: int = 5) -> str:
    """
    Turn retrieved rows into a single plain-text block for downstream LLM use.
    Hata durumunda boş string (sistem çökmez).
    """
    try:
        rows = retrieve_relevant_university_content(query, limit=limit)
        parts: list[str] = []
        for row in rows:
            body = (row.raw_text or "").strip() or (row.content_text or "").strip()
            excerpt = body
            if len(excerpt) > 2000:
                excerpt = excerpt[:2000].rstrip() + "…"
            header = f"[{row.source}] {row.title or row.source_url}"
            parts.append(f"{header}\nURL: {row.source_url}\n{excerpt}")
        return "\n\n---\n\n".join(parts)
    except Exception:
        logger.exception("build_context_bundle_for_ai failed")
        return ""
