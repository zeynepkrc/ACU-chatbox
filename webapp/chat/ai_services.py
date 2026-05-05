"""Local LLM generation (Ollama) wired to Şevval's retrieval bundle."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from services import build_context_bundle_for_ai


def _ollama_generate_url() -> str:
    base = (os.environ.get("OLLAMA_BASE_URL") or "http://ollama:11434").rstrip("/")
    return f"{base}/api/generate"


def _ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL") or "phi3:mini"


def _build_rag_prompt(user_query: str, context_block: str) -> str:
    system = (
        "You are the official virtual assistant for Acıbadem University (ACU). "
        "Answer clearly and professionally in the same language as the user's question "
        "(Turkish if they wrote Turkish, English if they wrote English).\n\n"
        "Rules:\n"
        "- Base your answer primarily on the RETRIEVED CONTEXT below. It comes from public university web pages.\n"
        "- If the context does not contain enough information, say so honestly and suggest visiting the relevant ACU page or office.\n"
        "- Do not invent facts, dates, fees, or program requirements that are not supported by the context.\n"
        "- Be concise unless the user asks for detail.\n"
    )
    ctx = context_block.strip() or "(No matching passages were found in the indexed content.)"
    return (
        f"{system}\n"
        f"=== RETRIEVED CONTEXT ===\n{ctx}\n"
        f"=== END CONTEXT ===\n\n"
        f"User question:\n{user_query.strip()}\n\n"
        "Assistant answer:"
    )


def ask_ai(user_query: str, *, context_limit: int = 10, timeout_sec: int = 180) -> str:
    """
    Retrieve context for ``user_query``, call Ollama ``/api/generate``, return assistant text.

    Uses ``OLLAMA_BASE_URL`` (default ``http://ollama:11434``) and ``OLLAMA_MODEL``.
    """
    q = (user_query or "").strip()
    if not q:
        return "Lütfen bir soru yazın."

    context = build_context_bundle_for_ai(q, limit=context_limit)
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
        raise RuntimeError(f"Ollama isteği başarısız ({url}): {exc}") from exc

    if resp.status_code >= 400:
        raise RuntimeError(
            f"Ollama HTTP {resp.status_code}: {resp.text[:500] if resp.text else 'no body'}"
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama yanıtı JSON değil.") from exc

    text = (data.get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama boş yanıt döndü.")
    return text
