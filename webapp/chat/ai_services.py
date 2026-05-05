"""Local LLM generation (Ollama) wired to Şevval's retrieval bundle."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from django.conf import settings
from django.db.models.functions import Length

from chat.models import ManualResponse

logger = logging.getLogger(__name__)

_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
_TOKEN_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+", re.UNICODE)
_OVERLAP_STOPWORDS: frozenset[str] = frozenset(
    {"ve", "veya", "ile", "için", "ama", "fakat", "gibi", "olan", "mı", "mi", "mu", "mü", "bir", "bu"}
)


def _ollama_generate_url() -> str:
    base = str(getattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")).rstrip("/")
    return f"{base}/api/generate"


def _ollama_model() -> str:
    return str(getattr(settings, "OLLAMA_MODEL", "qwen2.5:1.5b"))


def _request_timeout() -> tuple[float, float]:
    """(connect, read) — ağır modellerde okuma süresi uzun olabilir."""
    read_sec = float(int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SEC", 3600)))
    connect_sec = float(int(getattr(settings, "OLLAMA_REQUEST_CONNECT_SEC", 45)))
    return (connect_sec, read_sec)


def _manual_response_if_match(user_query: str) -> str | None:
    """
    Aktif ``ManualResponse`` kayıtlarında ``question_pattern`` alt dize eşleşmesi (casefold).
    Uzun kalıplar önce denenir (daha spesifik öncelik).
    """
    q = (user_query or "").strip()
    if not q:
        return None
    needle = q.casefold()
    try:
        rows = (
            ManualResponse.objects.filter(is_active=True)
            .exclude(question_pattern="")
            .annotate(_pat_len=Length("question_pattern"))
            .order_by("-_pat_len", "pk")
        )
        for row in rows:
            pat = (row.question_pattern or "").strip()
            if not pat:
                continue
            if pat.casefold() in needle:
                ans = (row.manual_answer or "").strip()
                if ans:
                    return ans
    except Exception:
        logger.exception("ManualResponse lookup failed")
    return None


def _build_rag_prompt(user_query: str, context_block: str) -> str:
    ctx = context_block.strip()
    return (
        "CONTEXT:\n"
        f"{ctx}\n\n"
        "QUESTION:\n"
        f"{user_query.strip()}\n\n"
        "TASK:\n"
        "Answer the QUESTION using ONLY the CONTEXT.\n\n"
        "Rules:\n"
        "* Do NOT use outside knowledge\n"
        "* Do NOT generate general explanations\n"
        "* Do NOT change topic\n"
        "* If the answer is not in CONTEXT, say: \"Bilmiyorum.\"\n"
        "* Answer in Turkish\n"
        "* Keep answer short (max 2 sentences)"
    )


def _tokenize_for_overlap(text: str) -> set[str]:
    out: set[str] = set()
    for t in _TOKEN_RE.findall((text or "").lower()):
        if len(t) < 3 or t in _OVERLAP_STOPWORDS:
            continue
        out.add(t)
    return out


def _relevance_score(question: str, context: str) -> float:
    q_tokens = _tokenize_for_overlap(question)
    if not q_tokens:
        return 0.0
    c_tokens = _tokenize_for_overlap(context)
    if not c_tokens:
        return 0.0
    overlap = q_tokens & c_tokens
    # Soru token kapsama oranı: modelden bağımsız basit ve genel relevance metriği.
    return len(overlap) / max(1, len(q_tokens))


def _sanitize_user_facing_answer(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw in (text or "").splitlines():
        ln = raw.strip()
        low = ln.lower()
        if not ln:
            continue
        if low.startswith("url:"):
            continue
        if low.startswith("[bologna]") or low.startswith("[main]"):
            continue
        if low.startswith("bölüm:") or low.startswith("program:") or low.startswith("section:"):
            continue
        if "source_url" in low or "chunk" in low:
            continue
        cleaned_lines.append(ln)
    out = " ".join(cleaned_lines).strip()
    out = re.sub(r"\s+", " ", out)
    return out


def ask_ai(user_query: str, *, context_limit: int | None = None, timeout_sec: int | None = None) -> str:
    """
    RAG + Ollama. Varsayılan bağlam sayısı ``settings.RAG_CONTEXT_MAX_DOCUMENTS`` (genelde 3).
    """
    try:
        connect_sec, read_sec = _request_timeout()
        if timeout_sec is not None:
            read_sec = float(timeout_sec)
            timeout_tuple: float | tuple[float, float] = (connect_sec, read_sec)
        else:
            timeout_tuple = (connect_sec, read_sec)

        if context_limit is None:
            context_limit = int(getattr(settings, "RAG_CONTEXT_MAX_DOCUMENTS", 3))
        context_limit = max(1, min(int(context_limit), 8))

        q = (user_query or "").strip()
        if not q:
            return "Lütfen bir soru yazın."

        manual = _manual_response_if_match(q)
        if manual is not None:
            return manual

        context = ""
        debug_docs: list[dict[str, str]] = []
        try:
            from services import build_context_bundle_for_ai_with_meta

            context, debug_docs = build_context_bundle_for_ai_with_meta(q, limit=context_limit)
        except Exception:
            logger.exception("Context retrieval import or build failed")
            context = ""

        logger.info("RAG request question=%r", q)
        logger.info("RAG retrieved docs=%s", debug_docs)
        logger.info("RAG retrieved context preview=%r", context[:1200])
        print("QUESTION:", q)
        print("DOC COUNT:", len(debug_docs))
        print("CONTEXT:", context)
        print(
            "DOC TITLES/SOURCES:",
            [f"{(d.get('title') or '').strip()} | {(d.get('source') or '').strip()}" for d in debug_docs],
        )
        if not context.strip():
            logger.info("RAG empty/irrelevant context; returning Bilmiyorum.")
            return "Bilmiyorum."
        relevance = _relevance_score(q, context)
        logger.info("RAG relevance score=%.3f", relevance)
        if relevance < 0.25:
            logger.info("RAG relevance below threshold; returning Bilmiyorum without model call.")
            return "Bilmiyorum."

        prompt = _build_rag_prompt(q, context)

        payload: dict[str, Any] = {
            "model": _ollama_model(),
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "top_p": 0.3,
                "repeat_penalty": 1.1,
                "num_predict": 120,
            },
        }

        url = _ollama_generate_url()
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=_JSON_HEADERS,
                timeout=timeout_tuple,
            )
        except requests.RequestException as exc:
            logger.exception("Ollama HTTP request failed")
            return (
                "Şu an yapay zekâ sunucusuna bağlanılamadı veya süre aşıldı. "
                "Model (ör. qwen2.5:7b) CPU'da uzun sürebilir; bir süre sonra tekrar deneyin. "
                f"(Ayrıntı: {exc})"
            )

        if resp.status_code >= 400:
            body = (resp.text or "")[:500]
            logger.warning("Ollama HTTP %s: %s", resp.status_code, body)
            return (
                "Model şu an yanıt üretemedi (sunucu hatası). "
                f"HTTP {resp.status_code}. Tekrar deneyin veya yöneticiye bildirin."
            )

        try:
            data = resp.json()
        except json.JSONDecodeError:
            logger.exception("Ollama returned non-JSON")
            return "Model yanıtı okunamadı. Lütfen tekrar deneyin."

        text = (data.get("response") or "").strip()
        if not text:
            return "Bilmiyorum."
        text = _sanitize_user_facing_answer(text)
        if not text:
            return "Bilmiyorum."

        return text
    except Exception as exc:
        logger.exception("ask_ai unexpected failure")
        return (
            "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin. "
            f"({type(exc).__name__}: {exc})"
        )
