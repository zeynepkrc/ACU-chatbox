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
    payload.update(extra)
    return JsonResponse(payload, status=status)


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


@csrf_exempt
@require_http_methods(["POST"])
def chat_api(request):
    """
    POST JSON. Her durumda JSON yanıt (HTML üretilmez).
    """
    try:
        try:
            raw = request.body.decode("utf-8") if request.body else ""
            data = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
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
            payload = {
                "ok": False,
                "error": f"Üretim hatası: {exc}",
                "code": "generation_error",
            }
            if settings.DEBUG:
                payload["traceback"] = traceback.format_exc()
            return JsonResponse(payload, status=502)

        if not isinstance(answer, str):
            answer = str(answer)

        try:
            ChatHistory.objects.create(user_query=user_query, ai_response=answer)
        except Exception as exc:
            logger.exception("ChatHistory save failed")
            payload = {
                "ok": True,
                "answer": answer,
                "query": user_query,
                "warning": "history_not_saved",
            }
            if settings.DEBUG:
                payload["history_error"] = str(exc)
            return JsonResponse(payload, status=200)

        return JsonResponse({"ok": True, "answer": answer, "query": user_query})

    except Exception as exc:
        logger.exception("chat_api fatal failure")
        payload = {
            "ok": False,
            "error": "Sunucu hatası.",
            "code": "internal_error",
            "detail": str(exc),
        }
        if settings.DEBUG:
            payload["traceback"] = traceback.format_exc()
        return JsonResponse(payload, status=500)
