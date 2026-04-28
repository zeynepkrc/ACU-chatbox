from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from .models import PageContent, ChatMessage


def find_relevant_content(question):
    words = question.lower().split()

    query = Q()

    for word in words:
        query |= Q(content__icontains=word)
        query |= Q(title__icontains=word)

    return PageContent.objects.filter(query)


def home(request):
    question = request.GET.get("q", "")
    answer = ""

    if question:
        results = find_relevant_content(question)

        if results.exists():
            answer = results.first().content
        else:
            answer = "No relevant information found."

        ChatMessage.objects.create(question=question, answer=answer)

    return render(request, "chat/home.html", {
        "question": question,
        "answer": answer,
    })


def chat(request):
    question = request.GET.get("q", "")

    if not question:
        return JsonResponse({
            "error": "Please provide a question using ?q=..."
        })

    results = find_relevant_content(question)

    if results.exists():
        answer = results.first().content
    else:
        answer = "No relevant information found."

    ChatMessage.objects.create(question=question, answer=answer)

    return JsonResponse({
        "question": question,
        "answer": answer
    })