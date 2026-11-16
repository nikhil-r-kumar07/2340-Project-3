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


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


# `or` also covers a blank value like SECRET_KEY="" in .env
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-insecure-key"
DEBUG = env_bool("DEBUG")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

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
        "NAME": Path(os.getenv("DATABASE_PATH", BASE_DIR / "db.sqlite3")).expanduser(),
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

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # used by `collectstatic` when deploying

# Enable these in production after HTTPS is active. Keeping them environment-driven
# lets the local HTTP development server continue to work.
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", SECURE_SSL_REDIRECT)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD")
SILENCED_SYSTEM_CHECKS = env_list("SILENCED_SYSTEM_CHECKS")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- LLM settings (any OpenAI-compatible chat API: Groq, Ollama, etc.) ---
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")

# RAG settings (stories 3 + 4). All paths must be on persistent, writable storage.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).expanduser()
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", BASE_DIR / "chroma_db")).expanduser()
EMBED_CACHE_DIR = Path(os.getenv("EMBED_CACHE_DIR", BASE_DIR / ".model_cache")).expanduser()
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local").strip().lower()
EMBED_MODEL = os.getenv(
    "EMBED_MODEL",
    (
        "sentence-transformers/all-MiniLM-L6-v2"
        if EMBED_PROVIDER == "huggingface"
        else "BAAI/bge-small-en-v1.5"
    ),
)
HF_TOKEN = os.getenv("HF_TOKEN", "")
EMBED_API_TIMEOUT = int(os.getenv("EMBED_API_TIMEOUT", "60"))
EMBED_CHUNK_SIZE = int(os.getenv(
    "EMBED_CHUNK_SIZE",
    "240" if EMBED_PROVIDER == "huggingface" else "384",
))
EMBED_CHUNK_OVERLAP = int(os.getenv(
    "EMBED_CHUNK_OVERLAP",
    "40" if EMBED_PROVIDER == "huggingface" else "64",
))
EMBED_QUERY_PREFIX = os.getenv(
    "EMBED_QUERY_PREFIX",
    (
        "Represent this sentence for searching relevant passages: "
        if "bge-" in EMBED_MODEL.lower()
        else ""
    ),
)
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))  # passages given to the model per question
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.45"))  # ignore passages beyond this
