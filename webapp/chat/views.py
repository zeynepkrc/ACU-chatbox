from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from .models import PageContent, ChatMessage
import requests


OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"


def find_relevant_content(question):
    words = question.lower().split()
    query = Q()

    for word in words:
        query |= Q(content__icontains=word)
        query |= Q(title__icontains=word)

    return PageContent.objects.filter(query)[:3]


def ask_ollama(question, context):
    prompt = f"""
You are a factual AI assistant for Acıbadem University.

STRICT RULES:
- ONLY use the information in the context.
- DO NOT guess.
- DO NOT add extra explanations.
- DO NOT say "it can be considered" or similar phrases.
- Give a short, direct answer.
- If the answer is not clearly in the context, say:
  - "I don't have enough information about this." in English
  - "Bu konuda yeterli bilgim yok." in Turkish

LANGUAGE RULE:
- Answer in the SAME language as the question.
- If the context is in a different language, translate it before answering.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        },
        timeout=60
    )

    response.raise_for_status()
    return response.json().get("response", "").strip()


def get_answer(question):
    results = find_relevant_content(question)

    if not results:
        return "No relevant information found.", []

    context = "\n\n".join([item.content for item in results])
    sources = [results[0].url]

    try:
        answer = ask_ollama(question, context)
    except requests.RequestException:
        answer = "AI service is currently unavailable."

    return answer, sources


def home(request):
    question = request.GET.get("q", "")
    answer = ""
    sources = []

    if question:
        answer, sources = get_answer(question)
        ChatMessage.objects.create(question=question, answer=answer)

    return render(request, "chat/home.html", {
        "question": question,
        "answer": answer,
        "sources": sources
    })

    if question:
        answer = get_answer(question)
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

    answer = get_answer(question)
    ChatMessage.objects.create(question=question, answer=answer)

    return JsonResponse({
        "question": question,
        "answer": answer
    })