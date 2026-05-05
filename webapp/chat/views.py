import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .ai_services import ask_ai
from .models import ChatHistory

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def chat_api(request):
    """
    POST JSON body: {"query": "..."} (aliases: ``message``, ``question``).

    Returns JSON: ``{"ok": true, "answer": "...", "query": "..."}`` on success.
    """
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    user_query = (
        data.get("query")
        or data.get("message")
        or data.get("question")
        or ""
    )
    user_query = str(user_query).strip()
    if not user_query:
        return JsonResponse({"ok": False, "error": "missing_query"}, status=400)

    try:
        answer = ask_ai(user_query)
    except RuntimeError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:
        logger.exception("ask_ai failed")
        return JsonResponse({"ok": False, "error": "generation_failed"}, status=500)

    ChatHistory.objects.create(user_query=user_query, ai_response=answer)
    return JsonResponse({"ok": True, "answer": answer, "query": user_query})
