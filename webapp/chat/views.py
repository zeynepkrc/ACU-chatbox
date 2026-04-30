from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from .models import PageContent, ChatMessage
import requests


OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = "qwen2.5:1.5b"


def find_relevant_content(question):
    words = question.lower().split()
    query = Q()

    for word in words:
        query |= Q(content__icontains=word)
        query |= Q(title__icontains=word)

    return PageContent.objects.filter(query)[:1]


def extract_relevant_sentences(text, question):
    sentences = text.split(".")
    q = question.lower()

    # Özel durum: erkek yurdu sorusu
    if "erkek" in q and "yurt" in q:
        for sentence in sentences:
            if "erkek" in sentence.lower() and "yurdu" in sentence.lower():
                return sentence.strip() + "."

    # Genel en alakalı cümle seçimi
    q_words = question.lower().split()
    best_sentence = ""
    best_score = 0

    for sentence in sentences:
        s = sentence.lower()
        score = sum(1 for w in q_words if w in s)

        if score > best_score:
            best_score = score
            best_sentence = sentence.strip()

    return best_sentence + "." if best_sentence else text[:300]


def ask_ollama(question, context):
    prompt = f"""
You are a strict factual assistant for Acıbadem University.

RULES:
- Use ONLY the context.
- Do NOT add outside information.
- Do NOT infer or assume.
- Do NOT mention details that are not explicitly written in the context.
- Focus on the most relevant sentence.
- Prefer specific details such as numbers, distances, dates, and locations.
- Do NOT copy long text directly.
- Answer in 1-2 short sentences.
- If the context does not clearly answer the question, say:
  - "I don't have enough information about this." in English
  - "Bu konuda yeterli bilgim yok." in Turkish
- Always prioritize the most specific factual details (such as distance, location, or important facts).
- If the context contains a clear key detail, include it in the answer.
- Keep the answer concise and direct.

LANGUAGE:
- If the question is in Turkish, answer ONLY in Turkish.
- If the question is in English, answer ONLY in English.
- Do NOT mix languages.
- Do NOT translate into another language.

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
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 120
            }
        },
        timeout=180
    )

    response.raise_for_status()
    return response.json().get("response", "").strip()


def get_answer(question):
    results = list(find_relevant_content(question))

    if not results:
        return "No relevant information found.", []

    source = results[0]
    relevant_text = extract_relevant_sentences(source.content, question)

    # Türkçe "nerede" sorularında modeli kullanma, direkt doğru cümleyi ver
    if "nerede" in question.lower():
        return relevant_text, [source.url]

    context = f"""
Title: {source.title}
Relevant information:
{relevant_text}
"""

    sources = [source.url]

    try:
        answer = ask_ollama(question, context)
    except Exception as e:
        print("OLLAMA ERROR:", e)
        answer = f"AI service error: {e}"

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
        "sources": sources,
    })


def chat(request):
    question = request.GET.get("q", "")

    if not question:
        return JsonResponse({"error": "Please provide a question using ?q=..."})

    answer, sources = get_answer(question)
    ChatMessage.objects.create(question=question, answer=answer)

    return JsonResponse({
        "question": question,
        "answer": answer,
        "sources": sources
    })