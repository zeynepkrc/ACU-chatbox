from django.http import HttpResponse, JsonResponse
from .models import PageContent

def home(request):
    return HttpResponse("ACU AI Chatbot is running.")

def chat(request):
    question = request.GET.get("q", "")

    if not question:
        return JsonResponse({
            "error": "Please provide a question using ?q=..."
        })

    results = PageContent.objects.filter(content__icontains=question)

    if results.exists():
        answer = results.first().content
    else:
        answer = "No relevant information found."

    return JsonResponse({
        "question": question,
        "answer": answer
    })