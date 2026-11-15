"""
Django settings for the Medicare Helper chatbot.

Secrets and anything that changes between computers (API keys, debug mode,
allowed hosts) are read from a .env file so they never end up in git.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from .env into os.environ
load_dotenv(BASE_DIR / ".env")

# `or` also covers a blank value like SECRET_KEY="" in .env
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-insecure-key"
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # used by `collectstatic` when deploying

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- LLM settings (any OpenAI-compatible chat API: Groq, Ollama, etc.) ---
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")

# Rag settings (stories 3 + 4)
DATA_DIR = BASE_DIR / "data" #sources.json and its listed pdfs
CHROMA_DIR = BASE_DIR / "chroma_db" #ChromaDB's on disk vector store
EMBED_CACHE_DIR = BASE_DIR / ".model_cache" #fastembed model files
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4")) #passages given to the model per question
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.45")) #max rag distance. passages past this is ignored
