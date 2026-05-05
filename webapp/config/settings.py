"""Django settings for the ACU chatbot backend."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# docker-compose içindeki ``db`` servisi; yerel runserver için ``localhost`` + yayınlanan port.
_DATABASE_HOST = os.environ.get("DATABASE_HOST", "localhost").lower().strip()
if _DATABASE_HOST in ("db", "postgres"):
    _DEFAULT_DATABASE_PORT = "5432"
else:
    # Host makineden Docker Postgres'e: compose varsayılanı 5433:5432
    _DEFAULT_DATABASE_PORT = os.environ.get("POSTGRES_PUBLISH_PORT", "5433")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-dev-key-change-me")

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "chat",
    "scraper",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "acu_chatbot"),
        "USER": os.environ.get("POSTGRES_USER", "acu"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "acu"),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", _DEFAULT_DATABASE_PORT),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Gunicorn statik dosya sunmaz; WhiteNoise ile /static/ altında servis edilir.
# DEBUG açıkken collectstatic gerekmeden STATICFILES_DIRS + app static kullanılır.
WHITENOISE_USE_FINDERS = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
]

# Ollama: Docker ağında servis adı ``ollama``; yerelde env ile override edin.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
# Qwen vb. ağır modeller CPU'da uzun sürebilir; connect kısa, okuma üst sınırlı tutulur.
OLLAMA_REQUEST_CONNECT_SEC = int(os.environ.get("OLLAMA_REQUEST_CONNECT_SEC", "45"))
OLLAMA_REQUEST_TIMEOUT_SEC = int(os.environ.get("OLLAMA_REQUEST_TIMEOUT_SEC", "3600"))
# RAG: bağlamda kullanılacak UniversityContent satırı (varsayılan 3; güçlü sunucuda artırılabilir).
RAG_CONTEXT_MAX_DOCUMENTS = int(os.environ.get("RAG_CONTEXT_MAX_DOCUMENTS", "3"))
