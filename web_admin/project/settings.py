from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get("WEB_ADMIN_SECRET_KEY", "web-admin-development-secret-key")
DEBUG = os.environ.get("WEB_ADMIN_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("WEB_ADMIN_ALLOWED_HOSTS", "*").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "web_admin.api",
    "web_admin.ui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "web_admin.project.urls"
WSGI_APPLICATION = "web_admin.project.wsgi.application"
ASGI_APPLICATION = "web_admin.project.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("WEB_ADMIN_SQLITE_PATH", str(BASE_DIR / ".web_admin.sqlite3")),
    }
}

LANGUAGE_CODE = "ja"
TIME_ZONE = os.environ.get("TZ", "Asia/Tokyo")
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/ui/login/"
LOGIN_REDIRECT_URL = "/ui/"
LOGOUT_REDIRECT_URL = "/ui/login/"
