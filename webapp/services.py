"""Retrieval helpers for RAG-style context (independent of scraper code)."""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, QuerySet, When

from chat.models import UniversityContent


def retrieve_relevant_university_content(
    query: str,
    *,
    limit: int = 10,
) -> QuerySet[UniversityContent]:
    """
    Return rows from ``UniversityContent`` most likely useful as LLM context.

    Uses case-insensitive substring match on ``title`` and ``content_text`` (no
    extra DB extensions). Rows whose ``title`` contains the full query are
    ranked first; then newer ``updated_at`` wins as a weak tie-breaker.
    """
    text = (query or "").strip()
    if not text:
        return UniversityContent.objects.none()

    words = [w for w in text.split() if len(w) >= 2]
    if not words:
        words = [text]

    combined = Q()
    for w in words:
        combined |= Q(title__icontains=w) | Q(content_text__icontains=w)

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


def build_context_bundle_for_ai(query: str, *, limit: int = 10) -> str:
    """
    Turn retrieved rows into a single plain-text block for downstream LLM use.

    Each chunk includes title, URL, and a trimmed body excerpt.
    """
    rows = retrieve_relevant_university_content(query, limit=limit)
    parts: list[str] = []
    for row in rows:
        excerpt = (row.content_text or "").strip()
        if len(excerpt) > 2000:
            excerpt = excerpt[:2000].rstrip() + "…"
        header = f"[{row.source}] {row.title or row.source_url}"
        parts.append(f"{header}\nURL: {row.source_url}\n{excerpt}")
    return "\n\n---\n\n".join(parts)
