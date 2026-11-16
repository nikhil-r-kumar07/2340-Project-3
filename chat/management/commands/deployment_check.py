"""Fail-fast deployment readiness checks for the complete application."""

import importlib.util
import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import checks
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError


PLACEHOLDERS = {"", "CHANGE_ME", "your-groq-api-key"}
# These settings should remain false on a shared pythonanywhere.com subdomain.
# The account does not control every related hostname or the parent domain.
SHARED_HOST_HSTS_WARNINGS = {"security.W005", "security.W021"}


def nearest_existing_parent(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


class Command(BaseCommand):
    help = "Check security, dependencies, storage, data, and accounts before deployment."
    requires_system_checks = []

    def handle(self, *args, **options):
        failures = []

        for issue in checks.run_checks(include_deployment_checks=True):
            if (
                issue.id not in SHARED_HOST_HSTS_WARNINGS
                and issue.is_serious(checks.WARNING)
            ):
                failures.append(f"{issue.id}: {issue.msg}")

        if settings.DEBUG:
            failures.append("DEBUG must be False.")
        if settings.LLM_API_KEY.strip() in PLACEHOLDERS:
            failures.append("LLM_API_KEY is missing or still contains a placeholder.")
        if settings.EMBED_PROVIDER not in {"local", "huggingface"}:
            failures.append("EMBED_PROVIDER must be either 'local' or 'huggingface'.")
        if (
            settings.EMBED_PROVIDER == "huggingface"
            and settings.HF_TOKEN.strip() in PLACEHOLDERS
        ):
            failures.append(
                "HF_TOKEN is required when EMBED_PROVIDER=huggingface."
            )

        packages = ["chromadb", "pypdf", "requests", "semchunk"]
        if settings.EMBED_PROVIDER == "local":
            packages.append("fastembed")
        for package in packages:
            if importlib.util.find_spec(package) is None:
                failures.append(f"Required Python package is missing: {package}.")

        persistent_paths = {
            "database": Path(settings.DATABASES["default"]["NAME"]).parent,
            "source data": settings.DATA_DIR,
            "ChromaDB": settings.CHROMA_DIR,
        }
        if settings.EMBED_PROVIDER == "local":
            persistent_paths["embedding cache"] = settings.EMBED_CACHE_DIR
        for label, path in persistent_paths.items():
            existing_parent = nearest_existing_parent(path)
            if not os.access(existing_parent, os.W_OK):
                failures.append(
                    f"The {label} path is not writable: {path} "
                    f"(nearest existing parent: {existing_parent})."
                )

        manifest_path = settings.DATA_DIR / "sources.json"
        try:
            sources = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(sources, list) or not sources:
                failures.append(f"Source manifest is empty or invalid: {manifest_path}.")
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"Could not read source manifest {manifest_path}: {error}.")

        if not settings.STATIC_ROOT.exists() or not any(settings.STATIC_ROOT.iterdir()):
            failures.append(
                f"Collected static files were not found in {settings.STATIC_ROOT}; "
                "run 'python manage.py collectstatic --noinput'."
            )

        if not settings.CHROMA_DIR.exists() or not any(settings.CHROMA_DIR.iterdir()):
            failures.append(
                f"The RAG index is empty at {settings.CHROMA_DIR}; "
                "run 'python manage.py ingest'."
            )

        try:
            has_developer = get_user_model().objects.filter(
                is_active=True,
                is_staff=True,
            ).exists()
            if not has_developer:
                failures.append("No active developer account (is_staff=True) exists.")
        except DatabaseError as error:
            failures.append(f"Database is not ready; run migrations first: {error}.")

        if failures:
            details = "\n".join(f"  - {failure}" for failure in failures)
            raise CommandError(f"Deployment is not ready:\n{details}")

        self.stdout.write(self.style.SUCCESS("Deployment readiness checks passed."))
