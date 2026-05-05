"""Local LLM generation (Ollama) wired to Şevval's retrieval bundle."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _ollama_generate_url() -> str:
    base = str(getattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")).rstrip("/")
    return f"{base}/api/generate"


def _ollama_model() -> str:
    return str(getattr(settings, "OLLAMA_MODEL", "phi3:mini"))


def _build_rag_prompt(user_query: str, context_block: str) -> str:
    has_ctx = bool((context_block or "").strip())
    if has_ctx:
        system = (
            "You are the official virtual assistant for Acıbadem University (ACU). "
            "Answer clearly and professionally in the same language as the user's question "
            "(Turkish if they wrote Turkish, English if they wrote English).\n\n"
            "Rules:\n"
            "- Base your answer primarily on the RETRIEVED CONTEXT below (public university pages).\n"
            "- If the context does not fully answer the question, combine it with careful reasoning; "
            "do not invent specific ACU fees, dates, or program rules not supported by the context.\n"
            "- Be concise unless the user asks for detail.\n"
        )
        ctx = context_block.strip()
    else:
        system = (
            "You are a helpful assistant for users asking about Acıbadem University (ACU). "
            "INDEXED CONTEXT: none (no matching rows in the database, or DB unavailable).\n"
            "Instructions:\n"
            "- For greetings or general/educational questions (e.g. what the Bologna Process is), "
            "answer briefly using general knowledge in the user's language.\n"
            "- For Acıbadem-specific facts (programs, fees, deadlines, contacts), say you cannot verify "
            "them without indexed content and suggest checking https://www.acibadem.edu.tr or OBS.\n"
            "- Do not fabricate ACU-specific details.\n"
        )
        ctx = "(No indexed passages — answer within the rules above.)"

    return (
        f"{system}\n"
        f"=== RETRIEVED CONTEXT ===\n{ctx}\n"
        f"=== END CONTEXT ===\n\n"
        f"User question:\n{user_query.strip()}\n\n"
        "Assistant answer:"
    )


def ask_ai(user_query: str, *, context_limit: int | None = None, timeout_sec: int | None = None) -> str:
    """
    RAG + Ollama. Varsayılan 3–5 belge (settings.RAG_CONTEXT_MAX_DOCUMENTS).
    Bağlam yoksa veya DB hata verirse genel yanıt modu kullanılır; beklenmeyen hatalar yakalanır.
    """
    try:
        if timeout_sec is None:
            timeout_sec = int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SEC", 1800))
        if context_limit is None:
            context_limit = int(getattr(settings, "RAG_CONTEXT_MAX_DOCUMENTS", 5))
        context_limit = max(3, min(int(context_limit), 5))

        q = (user_query or "").strip()
        if not q:
            return "Lütfen bir soru yazın."

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
            resp = requests.post(url, json=payload, timeout=timeout_sec)
        except requests.RequestException as exc:
            logger.exception("Ollama HTTP request failed")
            return (
                "Şu an yapay zekâ sunucusuna bağlanılamadı veya süre aşıldı. "
                f"Lütfen tekrar deneyin. (Ollama: {exc})"
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
