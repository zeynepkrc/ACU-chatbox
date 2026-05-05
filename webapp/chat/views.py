import json
import logging
import traceback

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .ai_services import ask_ai
from .models import ChatHistory

logger = logging.getLogger(__name__)


def _json_error(status: int, code: str, message: str, **extra) -> JsonResponse:
    payload = {"ok": False, "error": message, "code": code}
    for key, val in extra.items():
        if val is not None:
            payload[key] = val
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def _json_ok(**payload) -> JsonResponse:
    body = {"ok": True, **payload}
    return JsonResponse(body, status=200, json_dumps_params={"ensure_ascii": False})


@require_http_methods(["GET"])
def test_chat(request):
    """Geçici test arayüzü (Berya üretim UI'ına kadar)."""
    try:
        return render(request, "chat/test_chat.html")
    except Exception as exc:
        logger.exception("test_chat render failed")
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Test sohbet</title></head>"
            "<body><p>Şablon yüklenemedi. API: <code>POST /api/chat/</code></p>"
            f"<pre>{exc}</pre></body></html>"
        )
        return HttpResponse(html, status=200, content_type="text/html; charset=utf-8")


def chat_ui(request):
    recent = list(ChatHistory.objects.order_by("-created_at")[:10])
    recent.reverse()
    chat_messages = []
    for row in recent:
        chat_messages.append({"role": "user", "body": row.user_query})
        chat_messages.append({"role": "assistant", "body": row.ai_response})
    return render(
        request,
        "chat/index.html",
        {"chat_messages": chat_messages},
    )


@csrf_exempt
@require_http_methods(["POST"])
def chat_api(request):
    """
    POST JSON. Her durumda JSON yanıt (HTML üretilmez).
    Üretim modeli: ``settings.OLLAMA_MODEL`` (ör. ``qwen2.5:7b``), Ollama ``OLLAMA_BASE_URL``.
    """
    try:
        try:
            raw = request.body.decode("utf-8") if request.body else ""
            data = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            logger.info("chat_api: invalid or empty JSON body")
            return _json_error(400, "invalid_json", "Geçersiz JSON gövdesi.")

        user_query = (
            data.get("query")
            or data.get("message")
            or data.get("question")
            or ""
        )
        try:
            user_query = str(user_query).strip()
        except Exception:
            user_query = ""

        if not user_query:
            return _json_error(400, "missing_query", "Soru metni gerekli (query / message / question).")

        try:
            answer = ask_ai(user_query)
        except Exception as exc:
            logger.exception("ask_ai raised unexpectedly")
            return _json_error(
                502,
                "generation_error",
                "Üretim sırasında bir hata oluştu. Lütfen tekrar deneyin.",
                detail=str(exc) if settings.DEBUG else None,
                traceback=traceback.format_exc() if settings.DEBUG else None,
            )

        if not isinstance(answer, str):
            answer = str(answer)
        answer = answer.strip()
        if not answer:
            logger.warning("chat_api: empty answer from ask_ai")
            answer = (
                "Yanıt üretilemedi. Soruyu biraz kısaltıp veya farklı kelimelerle tekrar deneyin; "
                "model yükü (qwen2.5) nedeniyle beklemek de gerekebilir."
            )

        model_name = getattr(settings, "OLLAMA_MODEL", "")

        try:
            ChatHistory.objects.create(user_query=user_query, ai_response=answer)
        except Exception as exc:
            logger.exception("ChatHistory save failed")
            extra = {"warning": "history_not_saved", "model": model_name}
            if settings.DEBUG:
                extra["history_error"] = str(exc)
            return _json_ok(answer=answer, query=user_query, **extra)

        return _json_ok(answer=answer, query=user_query, model=model_name)

    except Exception as exc:
        logger.exception("chat_api fatal failure")
        return _json_error(
            500,
            "internal_error",
            "Sunucu hatası. Lütfen kısa bir süre sonra tekrar deneyin.",
            detail=str(exc) if settings.DEBUG else None,
            traceback=traceback.format_exc() if settings.DEBUG else None,
        )
