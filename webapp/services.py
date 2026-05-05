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
_ACIBADEM_HINTS: tuple[str, ...] = (
    "acıbadem",
    "acibadem",
    "acıbadem üniversitesi",
    "acibadem universitesi",
    "acibadem.edu.tr",
    "obs.acibadem.edu.tr",
    "acu",
)
_IRRELEVANT_HINTS: tuple[str, ...] = (
    "acoustic",
    "akustik test",
    "vibration",
    "vibrasyon",
    "decibel",
    "desibel",
    "engineering report",
    "mühendislik raporu",
    "laboratuvar raporu",
)
_TR_STOPWORDS: frozenset[str] = frozenset(
    {"ve", "veya", "için", "ile", "mı", "mi", "mu", "mü", "bölüm", "bölümü", "var", "yok"}
)
_COURSE_CODE_RE = re.compile(r"\b([A-ZÇĞİÖŞÜ]{2,}\s*\d{3,4}[A-Z]?)\b")
_SEMESTER_RE = re.compile(r"\b([1-8])\s*\.?\s*(yarıyıl|yarıyil|dönem|donem)\b", re.I)
_ECTS_RE = re.compile(r"\b(3[0-9]|[1-2]?[0-9](?:[.,]\d+)?)\b")
_CONTEXT_CHAR_LIMIT = 2200
_BOLOGNA_NOISE_HINTS: tuple[str, ...] = (
    "bologna menü",
    "bologna menu",
    "kabuk / menü",
    "kabuk / menu",
    "program / detay",
)
_GENERIC_NOISE_HINTS: tuple[str, ...] = (
    "yükleniyor",
    "yukleniyor",
    "loading",
    "please wait",
)
_TABLE_LABEL_HINTS: frozenset[str] = frozenset(
    {
        "ders kodu",
        "ders adı",
        "ders adi",
        "dersin adı",
        "dersin adi",
        "zorunlu/seçmeli",
        "zorunlu / seçmeli",
        "zorunlu / secmeli",
        "akts",
        "ects",
        "öğretim yöntemi",
        "ogretim yontemi",
        "yarıyıl",
        "yariyil",
        "dönem",
        "donem",
    }
)
_NAV_NOISE_HINTS: tuple[str, ...] = (
    "ana sayfa",
    "home",
    "menu",
    "menü",
    "breadcrumb",
    "sayfayı yazdır",
    "copyright",
    "tüm hakları saklıdır",
    "kvkk",
    "gizlilik",
    "çerez",
    "cookie",
    "toggle navigation",
)
_SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "program_overview": ("hakkında", "tanıtım", "vizyon", "misyon", "program", "amaç", "hedef"),
    "course_plan": ("müfredat", "ders planı", "öğretim planı", "ders", "akts", "ects", "course"),
    "admission_fees_scholarship": ("başvuru", "kabul", "ücret", "burs", "kontenjan", "puan", "admission", "scholarship"),
    "accreditation": ("akreditasyon", "kalite", "değerlendirme", "accreditation"),
    "contact_location": ("iletişim", "adres", "kampüs", "location", "contact", "telefon", "e-posta", "eposta"),
}
_COURSE_INTENT_TERMS: tuple[str, ...] = (
    "ders",
    "course",
    "müfredat",
    "mufredat",
    "program planı",
    "program plani",
    "curriculum",
    "öğretim planı",
    "ogretim plani",
    "akts",
    "ects",
)
_OVERVIEW_SECTIONS: frozenset[str] = frozenset({"program_overview", "about", "introduction"})


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


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    text_l = (text or "").lower()
    return any(t in text_l for t in terms)


def _is_likely_turkish(text: str) -> bool:
    sample = (text or "").lower()
    if not sample:
        return False
    if any(ch in sample for ch in "çğıöşü"):
        return True
    words = {w for w in _TOKEN_RE.findall(sample) if len(w) >= 2}
    return len(words & _TR_STOPWORDS) >= 2


def _is_acibadem_related_row(row: UniversityContent) -> bool:
    blob = " ".join(
        [
            row.title or "",
            row.source or "",
            row.source_url or "",
            (row.raw_text or "")[:900],
            (row.content_text or "")[:900],
        ]
    )
    return _contains_any(blob, _ACIBADEM_HINTS)


def _is_obviously_irrelevant_row(row: UniversityContent) -> bool:
    blob = " ".join(
        [row.title or "", row.source or "", row.source_url or "", (row.raw_text or "")[:1200]]
    ).lower()
    return _contains_any(blob, _IRRELEVANT_HINTS) and not _contains_any(blob, _ACIBADEM_HINTS)


def _post_filter_rows(rows: list[UniversityContent], *, query: str, limit: int) -> list[UniversityContent]:
    if not rows:
        return []
    query_is_tr = _is_likely_turkish(query)
    filtered: list[UniversityContent] = []
    for row in rows:
        if not _is_acibadem_related_row(row):
            continue
        if _is_obviously_irrelevant_row(row):
            continue
        if query_is_tr:
            row_blob = " ".join([row.title or "", (row.raw_text or "")[:1200], (row.content_text or "")[:1200]])
            if not _is_likely_turkish(row_blob):
                continue
        filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def _clean_lines(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" -|\t")
        if not line or len(line) < 2:
            continue
        line_l = line.lower()
        if any(h in line_l for h in _BOLOGNA_NOISE_HINTS):
            continue
        if any(h in line_l for h in _NAV_NOISE_HINTS):
            continue
        if any(h in line_l for h in _GENERIC_NOISE_HINTS):
            continue
        if line_l.startswith("http") or line_l.startswith("www."):
            continue
        if line_l in _TABLE_LABEL_HINTS:
            continue
        if line_l in seen:
            continue
        seen.add(line_l)
        out.append(line)
    return out


def _is_course_list_query(query: str) -> bool:
    q = (query or "").lower()
    return any(k in q for k in _COURSE_INTENT_TERMS) or any(
        k in q for k in ("dersleri neler", "hangi ders", "ders listesi")
    )


def _extract_program_name(row: UniversityContent) -> str:
    title = (row.title or "").strip()
    if " - " in title:
        return title.split(" - ", 1)[0].strip()
    return title or "Program"


def _parse_bologna_course_rows(row: UniversityContent) -> list[dict[str, str]]:
    text = (row.content_text or "").strip() or (row.raw_text or "").strip()
    lines = _clean_lines(text)
    parsed: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    current_sem = ""
    program = _extract_program_name(row)
    last_header_signature = ""
    for line in lines:
        line_l = line.lower()
        sem_m = _SEMESTER_RE.search(line_l)
        if sem_m:
            current_sem = f"{sem_m.group(1)}. Yarıyıl"
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if not cells:
            continue
        header_like = [c.lower() for c in cells]
        if all(c in _TABLE_LABEL_HINTS for c in header_like):
            sig = "|".join(header_like)
            if sig == last_header_signature:
                continue
            last_header_signature = sig
            continue
        code = ""
        name = ""
        required = ""
        ects = ""
        method = ""
        for c in cells:
            cm = _COURSE_CODE_RE.search(c.upper())
            if cm and not code:
                code = cm.group(1).replace(" ", "")
            cl = c.lower()
            if not required and ("zorunlu" in cl or "seçmeli" in cl or "secmeli" in cl):
                required = "Zorunlu" if "zorunlu" in cl else "Seçmeli"
            if not method and any(m in cl for m in ("yüz yüze", "yuz yuze", "uzaktan", "online", "hibrit", "uygulama", "teorik")):
                method = c
            if not ects and ("akts" in cl or "ects" in cl):
                em = _ECTS_RE.search(cl.replace(",", "."))
                if em:
                    ects = em.group(1)
        if not ects:
            for c in cells:
                em = _ECTS_RE.fullmatch(c.replace(",", "."))
                if em:
                    ects = em.group(1)
                    break
        if code:
            for c in cells:
                cl = c.lower()
                if _COURSE_CODE_RE.search(c.upper()):
                    continue
                if any(x in cl for x in ("akts", "ects", "zorunlu", "seçmeli", "secmeli", "yüz yüze", "online", "uzaktan", "hibrit")):
                    continue
                if len(c) >= 4:
                    name = c
                    break
        if not (code and name):
            continue
        sem = current_sem or "Belirtilmemiş dönem"
        key = (sem.lower(), code.lower(), name.lower())
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "program": program,
                "semester": sem,
                "course_code": code,
                "course_name": name,
                "required_elective": required or "Belirtilmemiş",
                "ects": ects or "Belirtilmemiş",
                "teaching_method": method or "Belirtilmemiş",
            }
        )
    return parsed


def _format_bologna_courses_for_context(rows: list[dict[str, str]], *, names_only: bool) -> str:
    by_sem: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_sem.setdefault(r["semester"], []).append(r)
    sem_keys = sorted(by_sem.keys(), key=lambda s: int(re.findall(r"\d+", s)[0]) if re.findall(r"\d+", s) else 99)
    out: list[str] = []
    for sem in sem_keys:
        out.append(f"{sem}:")
        for r in by_sem[sem]:
            if names_only:
                out.append(f"- {r['course_name']}")
            else:
                out.append(
                    "- {code} | {name} | {req} | AKTS: {ects} | Öğretim: {method}".format(
                        code=r["course_code"],
                        name=r["course_name"],
                        req=r["required_elective"],
                        ects=r["ects"],
                        method=r["teaching_method"],
                    )
                )
    return "\n".join(out).strip()


def _semester_sort_key(semester: str) -> int:
    nums = re.findall(r"\d+", semester or "")
    return int(nums[0]) if nums else 99


def _query_requested_semesters(query: str) -> set[str]:
    out: set[str] = set()
    for m in re.finditer(r"\b([1-8])\s*\.?\s*(yarıyıl|yariyil|dönem|donem)\b", (query or "").lower()):
        out.add(f"{m.group(1)}. Yarıyıl")
    return out


def _dedupe_repeated_elective_blocks(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_sem: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_sem.setdefault(r["semester"], []).append(r)
    kept: list[dict[str, str]] = []
    seen_block_sig: set[tuple[str, str]] = set()
    for sem, sem_rows in by_sem.items():
        elective_names = sorted(
            {
                r["course_name"].strip().lower()
                for r in sem_rows
                if (r.get("required_elective") or "").strip().lower() == "seçmeli"
            }
        )
        block_sig = (sem.lower(), "|".join(elective_names))
        skip_electives = bool(elective_names) and block_sig in seen_block_sig
        if elective_names:
            seen_block_sig.add(block_sig)
        for r in sem_rows:
            if skip_electives and (r.get("required_elective") or "").strip().lower() == "seçmeli":
                continue
            kept.append(r)
    return kept


def _build_compact_row_context(row: UniversityContent, query: str) -> str:
    if row.source == UniversityContent.Source.BOLOGNA:
        course_rows = _parse_bologna_course_rows(row)
        if course_rows:
            course_rows = _dedupe_repeated_elective_blocks(course_rows)
            names_only = _is_course_list_query(query)
            requested_semesters = _query_requested_semesters(query)
            if requested_semesters:
                course_rows = [r for r in course_rows if r["semester"] in requested_semesters]
            else:
                semester_order = sorted({r["semester"] for r in course_rows}, key=_semester_sort_key)
                allowed = set(semester_order[:3])
                course_rows = [r for r in course_rows if r["semester"] in allowed]
            block = _format_bologna_courses_for_context(course_rows, names_only=names_only)
            if len(block) > 900:
                block = block[:900].rstrip() + "…"
            return f"{row.title or row.source_url}\n{block}".strip()
    chunks = _split_row_into_semantic_chunks(row)
    if not chunks:
        return ""
    keywords = extract_search_keywords(query, max_keywords=10)
    scored = sorted(
        ((_score_chunk_for_query(c, keywords, query), c) for c in chunks),
        key=lambda x: x[0],
        reverse=True,
    )
    top_chunks = [c for s, c in scored if s > 0][:3] or [scored[0][1]]
    out: list[str] = []
    for ch in top_chunks:
        out.append(f"{row.title or row.source_url}\n{ch['content']}".strip())
    return "\n\n".join(out)


def _row_to_candidate_chunks(row: UniversityContent, query: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if row.source == UniversityContent.Source.BOLOGNA:
        course_rows = _parse_bologna_course_rows(row)
        if course_rows:
            course_rows = _dedupe_repeated_elective_blocks(course_rows)
            requested_semesters = _query_requested_semesters(query)
            if requested_semesters:
                course_rows = [r for r in course_rows if r["semester"] in requested_semesters]
            names_only = _is_course_list_query(query)
            block = _format_bologna_courses_for_context(course_rows, names_only=names_only)
            if block:
                candidates.append(
                    {
                        "title": row.title or row.source_url,
                        "source": row.source,
                        "url": row.source_url,
                        "section": "course_plan",
                        "content": block[:900].rstrip() + ("…" if len(block) > 900 else ""),
                    }
                )
    for chunk in _split_row_into_semantic_chunks(row):
        candidates.append(chunk)
    return candidates


def _detect_page_type(title: str, text: str) -> str:
    blob = f"{title} {text}".lower()
    for section, kws in _SECTION_KEYWORDS.items():
        if any(k in blob for k in kws):
            return section
    return "other"


def _extract_program_faculty(title: str, url: str) -> tuple[str, str]:
    title_parts = [p.strip() for p in (title or "").split("-") if p.strip()]
    program = title_parts[0] if title_parts else ""
    faculty = ""
    path = url.lower()
    if "fakulte" in path or "fakülte" in path:
        faculty = "Fakülte"
    return program, faculty


def _split_by_headings(lines: list[str]) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] = []
    for ln in lines:
        is_heading = (
            len(ln) <= 70
            and not ln.endswith(".")
            and any(ch.isupper() for ch in ln[:2] + ln[-2:])
        )
        if is_heading and current:
            sections.append(current)
            current = [ln]
        else:
            current.append(ln)
    if current:
        sections.append(current)
    return sections


def _split_row_into_semantic_chunks(row: UniversityContent) -> list[dict[str, str]]:
    text = (row.content_text or "").strip() or (row.raw_text or "").strip()
    lines = _clean_lines(text)
    if not lines:
        return []
    program, faculty = _extract_program_faculty(row.title or "", row.source_url or "")
    raw_sections = _split_by_headings(lines)
    chunks: list[dict[str, str]] = []
    seen: set[str] = set()
    for sec in raw_sections:
        content = "\n".join(sec).strip()
        if len(content) < 60:
            continue
        if len(content) > 550:
            content = content[:550].rstrip() + "…"
        key = re.sub(r"\s+", " ", content).lower()
        if key in seen:
            continue
        seen.add(key)
        page_type = _detect_page_type(row.title or "", content)
        chunks.append(
            {
                "section": page_type,
                "content": content,
                "program": program,
                "faculty": faculty,
                "title": row.title or row.source_url,
                "source": row.source,
                "url": row.source_url,
            }
        )
    return chunks


def _score_chunk_for_query(chunk: dict[str, str], keywords: list[str], query: str) -> float:
    blob = f"{chunk.get('title','')} {chunk.get('section','')} {chunk.get('content','')}".lower()
    section = (chunk.get("section") or "other").lower()
    score = 0.0
    # 1) Keyword overlap (lexical relevance)
    for kw in keywords:
        kwl = kw.lower()
        if kwl in blob:
            score += 1.0 + min(blob.count(kwl), 4) * 0.4
    # 2) Semantic-ish coverage ratio (question token coverage in chunk)
    q_tokens = _tokenize_for_overlap_local(query)
    if q_tokens:
        matched = sum(1 for t in q_tokens if t in blob)
        score += (matched / max(1, len(q_tokens))) * 3.0
    # 3) Domain-specific boosts for course intent
    course_intent = _is_course_list_query(query)
    if course_intent:
        if section == "course_plan":
            score += 8.0
        elif section in _OVERVIEW_SECTIONS:
            score -= 2.5
        domain_hits = sum(1 for t in _COURSE_INTENT_TERMS if t in blob)
        score += min(domain_hits, 5) * 1.2
    else:
        # Non-course questions: keep neutral with slight bias against irrelevant overview-only chunks
        if section in _OVERVIEW_SECTIONS and len(keywords) >= 3:
            score -= 0.6
    return score


def _tokenize_for_overlap_local(text: str) -> set[str]:
    toks: set[str] = set()
    for t in _TOKEN_RE.findall((text or "").lower()):
        if len(t) < 3 or t in _STOPWORDS:
            continue
        toks.add(t)
    return toks


def _looks_like_list_content(text: str) -> bool:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return False
    bullet_like = sum(1 for ln in lines if ln.startswith("-") or re.match(r"^\d+[\).\s-]", ln))
    code_like = len(_COURSE_CODE_RE.findall(text.upper()))
    return bullet_like >= 2 or code_like >= 2


def _rerank_chunks_for_query(query: str, candidates: list[dict[str, str]], *, top_k: int = 3) -> list[dict[str, str]]:
    """
    Second-stage reranking after initial retrieval candidates.
    Combines keyword overlap + metadata section + content heuristics.
    """
    keywords = extract_search_keywords(query, max_keywords=12)
    course_intent = _is_course_list_query(query)
    scored: list[tuple[float, dict[str, str]]] = []
    for ch in candidates:
        section = (ch.get("section") or "other").lower()
        content = ch.get("content", "")
        score = _score_chunk_for_query(ch, keywords, query)

        # Metadata-aware preferences
        if course_intent and section in {"course_plan", "curriculum", "ders planı", "ders plani"}:
            score += 5.0
        if section in _OVERVIEW_SECTIONS:
            score -= 1.8 if course_intent else 0.5

        # Content heuristics
        if _looks_like_list_content(content):
            score += 1.8
        long_paragraph_penalty = max(0, len(re.findall(r"[.!?]", content)) - 6) * 0.15
        if len(content) > 520:
            long_paragraph_penalty += 0.6
        score -= long_paragraph_penalty

        scored.append((score, ch))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [ch for _, ch in scored[: max(2, min(top_k, 3))]]
    logger.info(
        "RAG rerank before=%s after=%s",
        [f"{(c.get('section') or 'other')}|{(c.get('title') or '')[:40]}" for c in candidates[:6]],
        [f"{(c.get('section') or 'other')}|{(c.get('title') or '')[:40]}" for c in top],
    )
    return top


def build_context_bundle_for_ai_with_meta(query: str, *, limit: int = 3) -> tuple[str, list[dict[str, str]]]:
    rows = list(retrieve_relevant_university_content(query, limit=limit))
    if not rows:
        return "", []
    docs = [{"title": (r.title or "").strip(), "source": (r.source or "").strip(), "url": (r.source_url or "").strip()} for r in rows]

    # Stage-1: initial retrieval candidates from matched rows
    initial_candidates: list[dict[str, str]] = []
    for r in rows:
        initial_candidates.extend(_row_to_candidate_chunks(r, query))

    # Stage-2: rerank candidates and keep only best 2-3 chunks
    reranked = _rerank_chunks_for_query(query, initial_candidates, top_k=3)
    parts: list[str] = []
    seen_chunks: set[str] = set()
    for ch in reranked:
        part = f"{ch.get('title') or ch.get('url')}\n{ch.get('content') or ''}".strip()
        key = re.sub(r"\s+", " ", part).lower()
        if key not in seen_chunks:
            seen_chunks.add(key)
            parts.append(part)
    context = "\n\n---\n\n".join(parts).strip()
    if len(context) > _CONTEXT_CHAR_LIMIT:
        context = context[:_CONTEXT_CHAR_LIMIT].rstrip() + "…"
    return context, docs


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
            filtered_fts = _post_filter_rows(fts_rows, query=text, limit=limit)
            if filtered_fts:
                return _queryset_in_order(filtered_fts)

        fallback_rows = _retrieve_via_keyword_scores(keywords, normalized_q, limit)
        if not fallback_rows:
            logger.debug(
                "RAG: no matching UniversityContent rows (keywords=%s)",
                keywords[:8],
            )
            return UniversityContent.objects.none()

        filtered_fallback = _post_filter_rows(fallback_rows, query=text, limit=limit)
        if not filtered_fallback:
            logger.debug("RAG: rows found but filtered as irrelevant/non-Acibadem")
            return UniversityContent.objects.none()

        return _queryset_in_order(filtered_fallback)
    except Exception:
        logger.exception("retrieve_relevant_university_content failed")
        return UniversityContent.objects.none()


def build_context_bundle_for_ai(query: str, *, limit: int = 3) -> str:
    """İlgili satırları tek düz metin bloğunda birleştirir."""
    try:
        context, _ = build_context_bundle_for_ai_with_meta(query, limit=limit)
        return context
    except Exception:
        logger.exception("build_context_bundle_for_ai failed")
        return ""
