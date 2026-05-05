"""Geçici: Ollama + RAG smoke testi (Docker: python test_ai.py)."""

import os
import sys

import django

# Django ayarlarını yükle (konteynerde çalışma dizini /app)
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from chat.ai_services import ask_ai

print("🚀 AI Testi Başlıyor (Bu işlem 30-60 sn sürebilir)...")
try:
    response = ask_ai("Acıbadem Üniversitesi hakkında kısa bilgi ver.")
    print("\n✅ AI CEVABI:\n", response)
except Exception as e:
    print("\n❌ HATA OLUŞTU:", str(e))
