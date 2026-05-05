"""Local LLM generation (Ollama) wired to Şevval's retrieval bundle."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings
from django.db.models.functions import Length

from chat.models import ManualResponse

logger = logging.getLogger(__name__)

_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def _ollama_generate_url() -> str:
    base = str(getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    return f"{base}/api/generate"


def _ollama_model() -> str:
    return str(getattr(settings, "OLLAMA_MODEL", "qwen2.5:7b"))


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
    has_ctx = bool((context_block or "").strip())
    if has_ctx:
        system = (
            "Sen bir Acıbadem Üniversitesi asistanısın. Sana sağlanan dokümanlardaki bilgileri kullanarak, "
            "dürüst ve akademik bir dille cevap ver. Kullanıcının sorusuyla aynı dilde yanıt ver "
            "(Türkçe soruda Türkçe, İngilizce soruda İngilizce).\n\n"
            "Kurallar:\n"
            "- Öncelikle RETRIEVED CONTEXT altındaki kurumsal kaynaklara dayan.\n"
            "- Dokümanda bilgi yoksa veya yetersizse, genel bilgini kullanabilirsin; bu durumda bunu "
            "açıkça belirt (ör. hangi kısmın dokümanda olmadığını kısaca söyle).\n"
            "- Acıbadem'e özel ücret, tarih, kontenjan gibi iddiaları dokümanda yoksa uydurma.\n"
            "- Gereksiz uzatma; kullanıcı ayrıntı istemedikçe özlü ol.\n"
        )
        ctx = context_block.strip()
    else:
        system = (
            "Sen bir Acıbadem Üniversitesi asistanısın. İndekslenmiş doküman bulunamadı veya veritabanı "
            "bağlamı yok.\n"
            "Talimatlar:\n"
            "- Selamlaşma veya genel eğitim konularında genel bilginle kısa yanıt ver; "
            "kaynak olmadığını belirt.\n"
            "- Acıbadem'e özel kesin bilgiler için https://www.acibadem.edu.tr veya OBS'e yönlendir; "
            "uydurma.\n"
            "- Dokümanda bilgi yoksa kendi genel bilgini kullanıyorsan bunu açıkça söyle.\n"
        )
        ctx = "(İndekslenmiş pasaj yok — yukarıdaki kurallara uy.)"

    return (
        f"{system}\n"
        f"=== RETRIEVED CONTEXT ===\n{ctx}\n"
        f"=== END CONTEXT ===\n\n"
        f"User question:\n{user_query.strip()}\n\n"
        "Assistant answer:"
    )


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
        try:
            from services import build_context_bundle_for_ai

            context = build_context_bundle_for_ai(q, limit=context_limit)
        except Exception:
            logger.exception("Context retrieval import or build failed")
            context = ""

        prompt = _build_rag_prompt(q, context)

        payload: dict[str, Any] = {
            "model": _ollama_model(),
            "prompt": prompt,
            "stream": False,
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
            return "Model boş yanıt döndü. Lütfen soruyu kısaltıp tekrar deneyin."

        return text
    except Exception as exc:
        logger.exception("ask_ai unexpected failure")
        return (
            "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin. "
            f"({type(exc).__name__}: {exc})"
        )
