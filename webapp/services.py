"""
RAG bağlamı: ``UniversityContent`` üzerinde arama (veri silinmez).

LLM çağrısı ``chat.ai_services`` / ``settings.OLLAMA_MODEL`` (ör. ``qwen2.5:7b``) ile yapılır.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Case, IntegerField, Q, QuerySet, When

from chat.models import UniversityContent

logger = logging.getLogger(__name__)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "ve", "veya", "ile", "için", "bir", "bu", "şu", "o", "de", "da", "ki",
        "mi", "mı", "mu", "mü", "ne", "nasıl", "neden", "niçin", "hangi",
        "çok", "daha", "en", "gibi", "kadar", "sonra", "önce", "her", "hiç",
        "değil", "var", "yok", "olan", "olarak", "bana", "sen", "biz", "siz",
        "onlar", "ben", "acaba", "lütfen", "hakkında", "ilgili", "şey", "diye",
        "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "at",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might",
        "what", "which", "who", "whom", "this", "that", "these", "those", "how",
        "why", "when", "where", "can", "about", "into", "through", "during",
        "with", "from", "by", "as", "if", "than", "too", "very", "just", "also",
    }
)

_TOKEN_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+", re.UNICODE)

_FALLBACK_CANDIDATE_CAP = 450


def extract_search_keywords(query: str, *, max_keywords: int = 14) -> list[str]:
    """Kullanıcı sorusundan anlamlı anahtar kelimeler (stopword elenmiş)."""
    raw = unicodedata.normalize("NFKC", (query or "").strip())
    if not raw:
        return []

    lower = raw.lower()
    tokens: list[str] = []
    seen: set[str] = set()
    for m in _TOKEN_RE.finditer(lower):
        t = m.group(0)
        if len(t) < 2 or t in _STOPWORDS:
            continue
        if t not in seen:
            seen.add(t)
            tokens.append(t)
        if len(tokens) >= max_keywords:
            break

    if not tokens:
        collapsed = re.sub(r"\s+", " ", lower).strip()
        if len(collapsed) >= 2:
            tokens = [collapsed[:80]]

    return tokens


def _build_keyword_or_q(keywords: Iterable[str]) -> Q | None:
    combined: Q | None = None
    for w in keywords:
        w = (w or "").strip()
        if len(w) < 2:
            continue
        part = (
            Q(title__icontains=w)
            | Q(content_text__icontains=w)
            | Q(raw_text__icontains=w)
        )
        combined = part if combined is None else combined | part
    return combined


def _score_row_for_keywords(row: UniversityContent, keywords: list[str], normalized_query: str) -> float:
    title_l = (row.title or "").lower()
    blob_l = f"{row.title or ''} {row.raw_text or ''} {row.content_text or ''}".lower()
    score = 0.0
    for kw in keywords:
        kl = kw.lower()
        if kl in title_l:
            score += 14.0
        occurrences = blob_l.count(kl)
        score += min(occurrences, 8) * 2.5
    if normalized_query and len(normalized_query) >= 3 and normalized_query in blob_l:
        score += 18.0
    return score


def _fts_retrieve_rows(keywords: list[str], limit: int) -> list[UniversityContent]:
    vector = (
        SearchVector("title", weight="A", config="simple")
        + SearchVector("raw_text", weight="B", config="simple")
        + SearchVector("content_text", weight="C", config="simple")
    )
    sq: SearchQuery | None = None
    for kw in keywords:
        token = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]+", " ", kw).strip()
        if len(token) < 2:
            continue
        part = SearchQuery(token, config="simple")
        sq = part if sq is None else sq | part
    if sq is None:
        return []

    qs = (
        UniversityContent.objects.annotate(rank=SearchRank(vector, sq))
        .filter(rank__gt=0)
        .order_by("-rank", "-updated_at")
    )
    return list(qs[:limit])


def _retrieve_via_keyword_scores(keywords: list[str], normalized_query: str, limit: int) -> list[UniversityContent]:
    q = _build_keyword_or_q(keywords)
    if q is None:
        return []

    candidates = list(
        UniversityContent.objects.filter(q)
        .distinct()
        .order_by("-updated_at")[:_FALLBACK_CANDIDATE_CAP]
    )
    scored = [(_score_row_for_keywords(row, keywords, normalized_query), row) for row in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[UniversityContent] = []
    for _, row in scored:
        if row not in out:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _queryset_in_order(rows: list[UniversityContent]) -> QuerySet[UniversityContent]:
    if not rows:
        return UniversityContent.objects.none()
    ids = [r.pk for r in rows]
    whens = [When(pk=pk, then=pos) for pos, pk in enumerate(ids)]
    return (
        UniversityContent.objects.filter(pk__in=ids)
        .annotate(_ord=Case(*whens, default=len(ids), output_field=IntegerField()))
        .order_by("_ord")
    )


def retrieve_relevant_university_content(
    query: str,
    *,
    limit: int = 3,
) -> QuerySet[UniversityContent]:
    """
    ``UniversityContent`` içinden en alakalı satırlar (yalnız okuma; veri silinmez).

    Önce PostgreSQL full-text + rank; sonuç yoksa anahtar kelime skorlaması.
    """
    try:
        text = (query or "").strip()
        if not text:
            return UniversityContent.objects.none()

        keywords = extract_search_keywords(text)
        if not keywords:
            logger.debug("RAG: no keywords extracted from query")
            return UniversityContent.objects.none()

        limit = max(1, min(int(limit), 10))
        normalized_q = unicodedata.normalize("NFKC", text).strip().lower()

        try:
            fts_rows = _fts_retrieve_rows(keywords, limit)
        except Exception:
            logger.exception("RAG: full-text retrieval failed; using keyword fallback")
            fts_rows = []

        if fts_rows:
            return _queryset_in_order(fts_rows)

        fallback_rows = _retrieve_via_keyword_scores(keywords, normalized_q, limit)
        if not fallback_rows:
            logger.debug(
                "RAG: no matching UniversityContent rows (keywords=%s)",
                keywords[:8],
            )
            return UniversityContent.objects.none()

        return _queryset_in_order(fallback_rows)
    except Exception:
        logger.exception("retrieve_relevant_university_content failed")
        return UniversityContent.objects.none()


def build_context_bundle_for_ai(query: str, *, limit: int = 3) -> str:
    """İlgili satırları tek düz metin bloğunda birleştirir."""
    try:
        rows = list(retrieve_relevant_university_content(query, limit=limit))
        if not rows:
            return ""

        parts: list[str] = []
        for row in rows:
            body = (row.raw_text or "").strip() or (row.content_text or "").strip()
            excerpt = body
            if len(excerpt) > 2200:
                excerpt = excerpt[:2200].rstrip() + "…"
            header = f"[{row.source}] {row.title or row.source_url}"
            parts.append(f"{header}\nURL: {row.source_url}\n{excerpt}")
        return "\n\n---\n\n".join(parts)
    except Exception:
        logger.exception("build_context_bundle_for_ai failed")
        return ""
